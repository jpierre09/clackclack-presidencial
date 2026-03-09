"""HTTP downloader for E-14 PDFs via Registraduría GraphQL API (AWS AppSync).

Auth flow:
  1. GET Cognito unauthenticated identity (Identity Pool)
  2. GET temporary AWS credentials
  3. Sign GraphQL requests with AWS SigV4

Queries used:
  departmentsTree  → department / municipality / zone / stand name maps
  allTransmissionCodes(condition: {idDepartmentCode, idTransmissionCodeStatus in [3,11]})

PDF URL pattern:
  {base}/assets/temis/pdf/{dep}/{mun}/{zone3}/{stand2}/{mesa3}/{acronym}/{expectedName}?uuid=…
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from backend import database as db
from backend.config import (
    CORP_CAM,
    CORP_SEN,
    DEPT_CODE,
    E14_DOWNLOADS_DIR,
    POLL_INTERVAL,
    REGISTRADURIA_BASE_URL,
)
from backend.services.event_bus import event_bus
from backend.services.local_ingest import ingest_file

log = logging.getLogger(__name__)

_PDF_BASE = f"{REGISTRADURIA_BASE_URL}/assets/temis/pdf"
_GQL_URL = "https://apx2e14awsprodcong.tps.net.co/graphql"
_GQL_HOST = "apx2e14awsprodcong.tps.net.co"
_GQL_REGION = "us-east-2"
_GQL_SERVICE = "appsync"
_IDENTITY_POOL_ID = "us-east-2:b3d8591c-b2ce-40b6-a96c-550c26f7bfd9"
_COGNITO_URL = "https://cognito-identity.us-east-2.amazonaws.com/"

_PDF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/143.0.0.0 Safari/537.36"
    ),
    "Referer": f"{REGISTRADURIA_BASE_URL}/departamento/01",
    "Origin": REGISTRADURIA_BASE_URL,
    "Accept": "application/pdf,*/*",
}

_CORP_ACRONYMS = {"001": "SEN", "002": "CAM"}


def _zfill(value, n: int) -> str:
    s = str(value or "")
    return s.zfill(n) if s.isdigit() else s


def _is_pdf(path: Path) -> bool:
    try:
        return path.read_bytes()[:5] == b"%PDF-"
    except OSError:
        return False


def _sanitize(name: str) -> str:
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "SIN_NOMBRE"


# ── AWS SigV4 helpers ──────────────────────────────────────────────────────────

def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k = _hmac_sha256(("AWS4" + secret_key).encode(), date_stamp)
    k = _hmac_sha256(k, region)
    k = _hmac_sha256(k, service)
    return _hmac_sha256(k, "aws4_request")


def _sigv4_headers(
    access_key: str,
    secret_key: str,
    session_token: str,
    body: str,
) -> dict:
    t = datetime.now(UTC)
    amz_date = t.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = t.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body.encode()).hexdigest()

    canon_headers = (
        f"content-type:application/json\n"
        f"host:{_GQL_HOST}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-security-token:{session_token}\n"
    )
    signed_headers = "content-type;host;x-amz-date;x-amz-security-token"
    canon_req = "\n".join(
        ["POST", "/graphql", "", canon_headers, signed_headers, payload_hash]
    )
    cred_scope = f"{date_stamp}/{_GQL_REGION}/{_GQL_SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            cred_scope,
            hashlib.sha256(canon_req.encode()).hexdigest(),
        ]
    )
    sk = _signing_key(secret_key, date_stamp, _GQL_REGION, _GQL_SERVICE)
    sig = hmac.new(sk, string_to_sign.encode(), hashlib.sha256).hexdigest()

    return {
        "Content-Type": "application/json",
        "Host": _GQL_HOST,
        "X-Amz-Date": amz_date,
        "X-Amz-Security-Token": session_token,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{cred_scope}, "
            f"SignedHeaders={signed_headers}, Signature={sig}"
        ),
    }


# ── GraphQL queries ────────────────────────────────────────────────────────────

_QUERY_DEPARTMENTS_TREE = """
query DepartmentsTree($first: Int = 500000) {
  departmentsTree(first: $first, orderBy: "DEPARTMENT_NAME_ASC") {
    edges {
      node {
        idDepartmentCode
        departmentName
        municipalities {
          municipalityCode
          municipalityName
          zones {
            idZoneCode
            zoneName
            stands {
              standCode
              standName
            }
          }
        }
      }
    }
  }
}
"""

_QUERY_TRANSMISSION_CODES = """
query AllTransmissionCodes($first: Int!, $status: Int!, $dept: String!, $corp: String!) {
  allTransmissionCodes(
    first: $first
    condition: {
      idTransmissionCodeStatus: $status
      idDepartmentCode: $dept
      idCorporationCode: $corp
    }
  ) {
    nodes {
      idDepartmentCode
      municipalityCode
      idZoneCode
      standCode
      numberStand
      idCorporationCode
      expectedName
      idTransmissionCodeStatus
    }
  }
}
"""
_PAGE_SIZE = 20000


class RemotePoller:
    def __init__(self):
        self._known_keys: set[str] = set()
        self._dept_names: dict[str, str] = {}
        self._mun_names: dict[str, str] = {}
        self._zone_names: dict[str, str] = {}
        self._stand_names: dict[str, str] = {}
        self._catalogs_loaded = False
        # Cognito credentials cache
        self._access_key: str = ""
        self._secret_key: str = ""
        self._session_token: str = ""
        self._creds_expiry: datetime = datetime.now(UTC)

    async def _get_creds(self, client: httpx.AsyncClient) -> bool:
        """Fetch/refresh temporary AWS credentials from Cognito Identity Pool."""
        if self._access_key and datetime.now(UTC) < self._creds_expiry - timedelta(minutes=5):
            return True  # Still valid

        cognito_headers = {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityService.GetId",
        }
        try:
            r1 = await client.post(
                _COGNITO_URL,
                json={"IdentityPoolId": _IDENTITY_POOL_ID},
                headers=cognito_headers,
                timeout=15,
            )
            r1.raise_for_status()
            identity_id = r1.json()["IdentityId"]

            r2 = await client.post(
                _COGNITO_URL,
                json={"IdentityId": identity_id},
                headers={**cognito_headers, "X-Amz-Target": "AWSCognitoIdentityService.GetCredentialsForIdentity"},
                timeout=15,
            )
            r2.raise_for_status()
            c = r2.json()["Credentials"]
            self._access_key = c["AccessKeyId"]
            self._secret_key = c["SecretKey"]
            self._session_token = c["SessionToken"]
            # Expiry is ISO8601 string like "2026-03-08T18:22:22Z"
            expiry_str = c.get("Expiration", "")
            try:
                self._creds_expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            except Exception:
                self._creds_expiry = datetime.now(UTC) + timedelta(hours=1)
            return True
        except Exception as exc:
            log.error("Cognito credentials failed: %s", exc)
            return False

    async def _gql(self, client: httpx.AsyncClient, query: str, variables: dict | None = None) -> dict | None:
        """Execute a GraphQL query against the AppSync endpoint."""
        body = json.dumps({"query": query, "variables": variables or {}})
        headers = _sigv4_headers(
            self._access_key, self._secret_key, self._session_token, body
        )
        try:
            r = await client.post(_GQL_URL, content=body, headers=headers, timeout=60)
            r.raise_for_status()
            result = r.json()
            if "errors" in result:
                log.error("GraphQL errors: %s", result["errors"])
                return None
            return result.get("data")
        except Exception as exc:
            log.error("GraphQL request failed: %s", exc)
            return None

    async def _load_catalogs(self, client: httpx.AsyncClient) -> bool:
        """Load name maps from DepartmentsTree GraphQL query."""
        data = await self._gql(client, _QUERY_DEPARTMENTS_TREE, {"first": 500000})
        if not data:
            return False

        for edge in (data.get("departmentsTree", {}).get("edges") or []):
            dep = str(edge.get("node", {}).get("idDepartmentCode") or "")
            self._dept_names[dep] = str(edge.get("node", {}).get("departmentName") or dep)
            for m in (edge.get("node", {}).get("municipalities") or []):
                mun = str(m.get("municipalityCode") or "")
                self._mun_names[f"{dep}|{mun}"] = str(m.get("municipalityName") or mun)
                for z in (m.get("zones") or []):
                    zone2 = str(z.get("idZoneCode") or "")
                    self._zone_names[f"{dep}|{mun}|{zone2}"] = str(z.get("zoneName") or zone2)
                    for s in (z.get("stands") or []):
                        stand2 = str(s.get("standCode") or "")
                        self._stand_names[f"{dep}|{mun}|{zone2}|{stand2}"] = str(
                            s.get("standName") or stand2
                        )

        self._catalogs_loaded = True
        log.info("Catalogs loaded: %d depts, %d muns, %d zones, %d stands",
                 len(self._dept_names), len(self._mun_names),
                 len(self._zone_names), len(self._stand_names))
        return True

    def _target_path(
        self,
        dep: str, mun: str, zone2: str, stand2: str,
        mesa3: str, acronym: str, expected_name: str,
    ) -> Path:
        dep_label = _sanitize(f"{dep}-{self._dept_names.get(dep, dep)}")
        mun_label = _sanitize(f"{mun}-{self._mun_names.get(f'{dep}|{mun}', mun)}")
        zone_label = _sanitize(
            f"{zone2}-{self._zone_names.get(f'{dep}|{mun}|{zone2}', zone2)}"
        )
        stand_label = _sanitize(
            f"{stand2}-{self._stand_names.get(f'{dep}|{mun}|{zone2}|{stand2}', stand2)}"
        )
        sub = (
            E14_DOWNLOADS_DIR
            / dep_label
            / mun_label
            / zone_label
            / stand_label
        )
        return sub / f"MESA_{mesa3}_{acronym}_{expected_name}"

    async def poll_once(self) -> dict:
        stats = {"fetched": 0, "downloaded": 0, "processed": 0, "skipped": 0, "errors": 0}

        async with httpx.AsyncClient(follow_redirects=True) as client:
            if not await self._get_creds(client):
                log.warning("Could not obtain AWS credentials — skipping poll")
                return stats

            if not self._catalogs_loaded:
                if not await self._load_catalogs(client):
                    log.warning("Catalogs not available yet")
                    return stats

            # Fetch per dept+corp+status combination (4 small queries instead of 2 huge ones)
            dept = DEPT_CODE if DEPT_CODE not in ("ALL", "") else "01"
            nodes: list[dict] = []
            for corp_code in ("001", "002"):  # SEN, CAM
                for status in (3, 11):
                    vars_ = {"first": _PAGE_SIZE, "status": status, "dept": dept, "corp": corp_code}
                    data = await self._gql(client, _QUERY_TRANSMISSION_CODES, vars_)
                    if not data:
                        log.warning("allTransmissionCodes dept=%s corp=%s status=%s failed", dept, corp_code, status)
                        continue
                    batch = data.get("allTransmissionCodes", {}).get("nodes") or []
                    nodes.extend(batch)
                    log.info("dept=%s corp=%s status=%s → %s records", dept, corp_code, status, len(batch))

            # Filter: published (status 3 or 11) + SEN and CAM only (dept already filtered in query)
            filtered = []
            for row in nodes:
                dep = str(row.get("idDepartmentCode") or "")
                status = row.get("idTransmissionCodeStatus")
                if status not in (3, 11):
                    continue
                corp3 = str(row.get("idCorporationCode") or "")
                acronym = _CORP_ACRONYMS.get(corp3)
                if acronym not in (CORP_SEN, CORP_CAM):
                    continue
                expected = str(row.get("expectedName") or "").strip()
                if not expected:
                    continue
                filtered.append((row, dep, corp3, acronym, expected))

            stats["fetched"] = len(filtered)
            if not filtered:
                log.info("No published E14s available for dept=%s yet", DEPT_CODE)
                return stats

            E14_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

            for row, dep, corp3, acronym, expected in filtered:
                mun = str(row.get("municipalityCode") or "")
                zone2 = str(row.get("idZoneCode") or "")
                zone3 = _zfill(zone2, 3)
                stand2 = str(row.get("standCode") or "")
                mesa3 = _zfill(row.get("numberStand"), 3)

                unique_key = f"{dep}|{mun}|{zone3}|{stand2}|{mesa3}|{corp3}|{expected}"
                if unique_key in self._known_keys:
                    stats["skipped"] += 1
                    continue

                target = self._target_path(dep, mun, zone2, stand2, mesa3, acronym, expected)

                if target.exists() and _is_pdf(target):
                    self._known_keys.add(unique_key)
                    stats["skipped"] += 1
                    continue

                pdf_url = (
                    f"{_PDF_BASE}/{dep}/{mun}/{zone3}/{stand2}/{mesa3}"
                    f"/{acronym}/{expected}?uuid={_uuid.uuid4()}"
                )

                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    r = await client.get(pdf_url, headers=_PDF_HEADERS, timeout=60)
                    r.raise_for_status()

                    target.write_bytes(r.content)

                    if not _is_pdf(target):
                        target.unlink(missing_ok=True)
                        log.warning("Not a valid PDF: %s", pdf_url)
                        stats["errors"] += 1
                        continue

                    self._known_keys.add(unique_key)
                    stats["downloaded"] += 1
                    log.info("Downloaded: %s", target.name)

                except Exception as exc:
                    log.error("Failed to download %s: %s", pdf_url, exc)
                    target.unlink(missing_ok=True)
                    stats["errors"] += 1
                    continue

                try:
                    ok, _ = await ingest_file(target)
                    if ok:
                        stats["processed"] += 1
                except Exception as exc:
                    log.error("Ingest failed for %s: %s", target, exc)
                    stats["errors"] += 1

        await event_bus.publish("remote_poll_complete", stats)
        return stats

    async def loop(self, stop_event: asyncio.Event):
        while not stop_event.is_set():
            try:
                result = await self.poll_once()
                log.info("Poll complete: %s", result)
            except Exception as exc:
                log.error("Poll loop error: %s", exc)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                continue


remote_poller = RemotePoller()
