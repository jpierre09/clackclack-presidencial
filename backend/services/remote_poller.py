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
import os
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from backend import database as db
from backend.config import (
    CORP_PRES,
    DEPT_CODE,
    E14_DOWNLOADS_DIR,
    POLL_INTERVAL,
    REGISTRADURIA_BASE_URL,
)
from backend.services.event_bus import event_bus
from backend.services.local_ingest import ingest_file

log = logging.getLogger(__name__)
POLL_LOCK = asyncio.Lock()
SKIP_STATUSES = {"processed", "corrected", "error"}

_PDF_BASE = f"{REGISTRADURIA_BASE_URL}/assets/temis/pdf"
# ── AppSync endpoints ─────────────────────────────────────────────────────────
# Presidencial (activo el día de elecciones) — ajustar si cambia el host
_GQL_HOST_PRES = os.getenv(
    "GQL_HOST_PRES",
    "apx2e14awsprodpres.tps.net.co",   # estimado; confirmar con el dominio real
)
# Fallback: usar el mismo host del congresional si el presidencial no está disponible
_GQL_HOST_CONG = "apx2e14awsprodcong.tps.net.co"
_GQL_HOST = _GQL_HOST_PRES
_GQL_URL  = f"https://{_GQL_HOST}/graphql"
_GQL_REGION   = "us-east-2"
_GQL_SERVICE  = "appsync"
_IDENTITY_POOL_ID = os.getenv(
    "AWS_IDENTITY_POOL_ID",
    "us-east-2:b3d8591c-b2ce-40b6-a96c-550c26f7bfd9",
)
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

_CORP_ACRONYMS = {"003": "PRES", "001": "PRES", "002": "PRES"}


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


def _result_key(mun: str, zone2: str, stand2: str, mesa3: str, acronym: str) -> tuple[str, str, str, int, str]:
    return (mun, _zfill(zone2, 2), stand2, int(mesa3), acronym)


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

_QUERY_TRANSMISSION_CODES_BY_MUN = """
query AllTransmissionCodesByMun($first: Int!, $status: Int!, $dept: String!, $corp: String!, $mun: String!) {
  allTransmissionCodes(
    first: $first
    condition: {
      idTransmissionCodeStatus: $status
      idDepartmentCode: $dept
      idCorporationCode: $corp
      municipalityCode: $mun
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

_QUERY_TRANSMISSION_CODES_BY_MUN_ZONE = """
query AllTransmissionCodesByMunZone($first: Int!, $status: Int!, $dept: String!, $corp: String!, $mun: String!, $zone: String!) {
  allTransmissionCodes(
    first: $first
    condition: {
      idTransmissionCodeStatus: $status
      idDepartmentCode: $dept
      idCorporationCode: $corp
      municipalityCode: $mun
      idZoneCode: $zone
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

_QUERY_TRANSMISSION_CODES_BY_MUN_ZONE_STAND = """
query AllTransmissionCodesByMunZoneStand($first: Int!, $status: Int!, $dept: String!, $corp: String!, $mun: String!, $zone: String!, $stand: String!) {
  allTransmissionCodes(
    first: $first
    condition: {
      idTransmissionCodeStatus: $status
      idDepartmentCode: $dept
      idCorporationCode: $corp
      municipalityCode: $mun
      idZoneCode: $zone
      standCode: $stand
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

_QUERY_TRANSMISSION_CODES_BY_MUN_NO_STATUS = """
query AllTransmissionCodesByMunNoStatus($first: Int!, $corp: String!, $mun: String!) {
  allTransmissionCodes(
    first: $first
    condition: {
      idCorporationCode: $corp
      municipalityCode: $mun
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
_MUN_PAGE_SIZE = 2000  # Per-municipality queries are much smaller
_ZONE_PAGE_SIZE = 2000
_STAND_PAGE_SIZE = 2000


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

    async def _load_existing_statuses(self) -> dict[tuple[str, str, str, int, str], str]:
        conn = await db.get_db()
        rows = await conn.execute_fetchall(
            """SELECT municipio_cod, zona_cod, puesto_cod, mesa, corporacion, status
               FROM e14_results"""
        )
        return {
            (
                row["municipio_cod"],
                row["zona_cod"],
                row["puesto_cod"],
                row["mesa"],
                row["corporacion"],
            ): row["status"]
            for row in rows
        }

    def _zone_codes_for_mun(self, dep: str, mun: str) -> list[str]:
        prefix = f"{dep}|{mun}|"
        return sorted(
            key.split("|")[2]
            for key in self._zone_names
            if key.startswith(prefix)
        )

    def _stand_codes_for_zone(self, dep: str, mun: str, zone2: str) -> list[str]:
        prefix = f"{dep}|{mun}|{zone2}|"
        return sorted(
            key.split("|")[3]
            for key in self._stand_names
            if key.startswith(prefix)
        )

    async def _query_status11_by_zone(
        self,
        client: httpx.AsyncClient,
        dept: str,
        corp_code: str,
        mun: str,
        zone2: str,
    ) -> list[dict]:
        data = await self._gql(
            client,
            _QUERY_TRANSMISSION_CODES_BY_MUN_ZONE,
            {
                "first": _ZONE_PAGE_SIZE,
                "status": 11,
                "dept": dept,
                "corp": corp_code,
                "mun": mun,
                "zone": zone2,
            },
        )
        zone_nodes = (data or {}).get("allTransmissionCodes", {}).get("nodes") or []
        if len(zone_nodes) < _ZONE_PAGE_SIZE:
            return zone_nodes

        stand_codes = self._stand_codes_for_zone(dept, mun, zone2)
        if not stand_codes:
            log.warning(
                "mun=%s zone=%s corp=%s status=11 truncated at %d without stand metadata; keeping partial batch",
                mun,
                zone2,
                corp_code,
                len(zone_nodes),
            )
            return zone_nodes

        log.warning(
            "mun=%s zone=%s corp=%s status=11 hit %d records; splitting into %d stand queries",
            mun,
            zone2,
            corp_code,
            len(zone_nodes),
            len(stand_codes),
        )

        stand_sem = asyncio.Semaphore(8)

        async def _query_stand(stand2: str) -> list[dict]:
            async with stand_sem:
                stand_data = await self._gql(
                    client,
                    _QUERY_TRANSMISSION_CODES_BY_MUN_ZONE_STAND,
                    {
                        "first": _STAND_PAGE_SIZE,
                        "status": 11,
                        "dept": dept,
                        "corp": corp_code,
                        "mun": mun,
                        "zone": zone2,
                        "stand": stand2,
                    },
                )
            stand_nodes = (stand_data or {}).get("allTransmissionCodes", {}).get("nodes") or []
            if len(stand_nodes) >= _STAND_PAGE_SIZE:
                log.warning(
                    "mun=%s zone=%s stand=%s corp=%s status=11 still hit %d records; review pagination strategy",
                    mun,
                    zone2,
                    stand2,
                    corp_code,
                    len(stand_nodes),
                )
            return stand_nodes

        parts = await asyncio.gather(*[_query_stand(stand2) for stand2 in stand_codes])
        flattened: list[dict] = []
        for part in parts:
            flattened.extend(part)
        return flattened

    async def _query_status11_by_mun(
        self,
        client: httpx.AsyncClient,
        dept: str,
        corp_code: str,
        mun: str,
    ) -> list[dict]:
        data = await self._gql(
            client,
            _QUERY_TRANSMISSION_CODES_BY_MUN,
            {
                "first": _MUN_PAGE_SIZE,
                "status": 11,
                "dept": dept,
                "corp": corp_code,
                "mun": mun,
            },
        )
        mun_nodes = (data or {}).get("allTransmissionCodes", {}).get("nodes") or []
        if len(mun_nodes) < _MUN_PAGE_SIZE:
            return mun_nodes

        zone_codes = self._zone_codes_for_mun(dept, mun)
        if not zone_codes:
            log.warning(
                "mun=%s corp=%s status=11 hit %d records without zone metadata; keeping partial batch",
                mun,
                corp_code,
                len(mun_nodes),
            )
            return mun_nodes

        log.warning(
            "mun=%s corp=%s status=11 hit %d records; splitting into %d zone queries",
            mun,
            corp_code,
            len(mun_nodes),
            len(zone_codes),
        )

        zone_sem = asyncio.Semaphore(8)

        async def _query_zone(zone2: str) -> list[dict]:
            async with zone_sem:
                return await self._query_status11_by_zone(client, dept, corp_code, mun, zone2)

        parts = await asyncio.gather(*[_query_zone(zone2) for zone2 in zone_codes])
        flattened: list[dict] = []
        for part in parts:
            flattened.extend(part)
        return flattened

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
        if POLL_LOCK.locked():
            log.info("Remote poll already in progress; waiting for current cycle")

        async with POLL_LOCK:
            existing_statuses = await self._load_existing_statuses()

            async with httpx.AsyncClient(follow_redirects=True) as client:
                if not await self._get_creds(client):
                    log.warning("Could not obtain AWS credentials — skipping poll")
                    return stats

                if not self._catalogs_loaded:
                    if not await self._load_catalogs(client):
                        log.warning("Catalogs not available yet")
                        return stats

                dept = DEPT_CODE if DEPT_CODE not in ("ALL", "") else "01"
                nodes: list[dict] = []

                # Get list of municipalities for this dept (used in per-mun fallback)
                dept_muns = [k.split("|")[1] for k in self._mun_names if k.startswith(dept + "|")]

                for corp_code in ("001", "002"):  # SEN, CAM
                    for status in (3, 11):
                        # status=11 responses exceed AppSync's 6 MB limit at dept level.
                        # Always query per-municipality for status=11 to guarantee full coverage.
                        if status == 3:
                            data = await self._gql(
                                client, _QUERY_TRANSMISSION_CODES,
                                {"first": _PAGE_SIZE, "status": status, "dept": dept, "corp": corp_code}
                            )
                        else:
                            data = None  # force per-mun path for status=11

                        if data is not None:
                            batch = data.get("allTransmissionCodes", {}).get("nodes") or []
                            nodes.extend(batch)
                            log.info("dept=%s corp=%s status=%s → %s records", dept, corp_code, status, len(batch))
                            continue

                        # Per-municipality queries (~125 small requests in parallel)
                        log.info("per-mun queries for corp=%s status=%s (%d muns)",
                                 corp_code, status, len(dept_muns))
                        mun_sem = asyncio.Semaphore(12)
                        mun_nodes: list[dict] = []

                        async def _query_mun(mun: str, _corp=corp_code, _status=status):
                            async with mun_sem:
                                if _status == 11:
                                    rows = await self._query_status11_by_mun(client, dept, _corp, mun)
                                else:
                                    d = await self._gql(
                                        client,
                                        _QUERY_TRANSMISSION_CODES_BY_MUN,
                                        {
                                            "first": _MUN_PAGE_SIZE,
                                            "status": _status,
                                            "dept": dept,
                                            "corp": _corp,
                                            "mun": mun,
                                        },
                                    )
                                    rows = (d or {}).get("allTransmissionCodes", {}).get("nodes") or []
                            mun_nodes.extend(rows)

                        await asyncio.gather(*[_query_mun(m) for m in dept_muns])
                        nodes.extend(mun_nodes)
                        log.info("per-mun corp=%s status=%s → %s records", corp_code, status, len(mun_nodes))

                # Filter: published (status 3 or 11) + SEN and CAM only (dept already filtered in query)
                filtered = []
                for row in nodes:
                    dep = str(row.get("idDepartmentCode") or "")
                    status = row.get("idTransmissionCodeStatus")
                    if status not in (3, 11):
                        continue
                    corp3 = str(row.get("idCorporationCode") or "")
                    acronym = _CORP_ACRONYMS.get(corp3)
                    if acronym not in (CORP_PRES,):
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

                # ── Phase 1: parallel downloads ────────────────────────────────────
                dl_sem = asyncio.Semaphore(20)

                async def _download_one(row, dep, corp3, acronym, expected):
                    mun = str(row.get("municipalityCode") or "")
                    zone2 = str(row.get("idZoneCode") or "")
                    zone3 = _zfill(zone2, 3)
                    stand2 = str(row.get("standCode") or "")
                    mesa3 = _zfill(row.get("numberStand"), 3)

                    result_key = _result_key(mun, zone2, stand2, mesa3, acronym)
                    if existing_statuses.get(result_key) in SKIP_STATUSES:
                        stats["skipped"] += 1
                        return None

                    unique_key = f"{dep}|{mun}|{zone3}|{stand2}|{mesa3}|{corp3}|{expected}"
                    if unique_key in self._known_keys:
                        stats["skipped"] += 1
                        return None

                    target = self._target_path(dep, mun, zone2, stand2, mesa3, acronym, expected)
                    if target.exists() and _is_pdf(target):
                        self._known_keys.add(unique_key)
                        existing_statuses[result_key] = "queued"
                        log.info("Reusing local PDF without DB skip: %s", target)
                        stats["skipped"] += 1
                        return target

                    pdf_url = (
                        f"{_PDF_BASE}/{dep}/{mun}/{zone3}/{stand2}/{mesa3}"
                        f"/{acronym}/{expected}?uuid={_uuid.uuid4()}"
                    )

                    async with dl_sem:
                        try:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            r = await client.get(pdf_url, headers=_PDF_HEADERS, timeout=60)
                            r.raise_for_status()
                            target.write_bytes(r.content)
                            if not _is_pdf(target):
                                target.unlink(missing_ok=True)
                                log.warning("Not a valid PDF: %s", pdf_url)
                                stats["errors"] += 1
                                return None
                            self._known_keys.add(unique_key)
                            existing_statuses[result_key] = "queued"
                            stats["downloaded"] += 1
                            return target
                        except Exception as exc:
                            log.error("Failed to download %s: %s", pdf_url, exc)
                            target.unlink(missing_ok=True)
                            stats["errors"] += 1
                            return None

                downloaded = await asyncio.gather(
                    *[_download_one(*args) for args in filtered]
                )

                # ── Phase 2: parallel OCR ingestion ───────────────────────────────
                ocr_sem = asyncio.Semaphore(8)

                async def _ingest_one(target):
                    if target is None:
                        return
                    async with ocr_sem:
                        try:
                            ok, reason = await ingest_file(target, retry_not_digitized=True)
                            if ok and reason == "processed":
                                stats["processed"] += 1
                        except Exception as exc:
                            log.error("Ingest failed for %s: %s", target, exc)
                            stats["errors"] += 1

                await asyncio.gather(*[_ingest_one(t) for t in downloaded])

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
