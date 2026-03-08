"""HTTP downloader for E-14 PDFs from Registraduría public API.

Polls:
  GET /assets/temis/divipol_json/allTransmissionCodes.json  → status3 + status11 nodes
  GET /assets/temis/divipol_json/allDepartments.json
  GET /assets/temis/divipol_json/allCorporations.json
  GET /assets/temis/divipol_json/departmentsTree.json

PDF URL pattern:
  /assets/temis/pdf/{dep}/{mun}/{zone3}/{stand2}/{mesa3}/{acronym}/{expectedName}?uuid={uuid}
"""
from __future__ import annotations

import asyncio
import logging
import uuid
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

_CATALOG_BASE = f"{REGISTRADURIA_BASE_URL}/assets/temis/divipol_json"
_PDF_BASE = f"{REGISTRADURIA_BASE_URL}/assets/temis/pdf"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/143.0.0.0 Safari/537.36"
    ),
    "Referer": f"{REGISTRADURIA_BASE_URL}/departamento/05",
    "Origin": REGISTRADURIA_BASE_URL,
    "Accept": "application/json,text/plain,*/*",
}

# Corporation code → acronym  (001=SEN, 002=CAM)
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
    invalid = r'\/:*?"<>|'
    for ch in invalid:
        name = name.replace(ch, "_")
    return name.strip() or "SIN_NOMBRE"


class RemotePoller:
    def __init__(self):
        self._known_keys: set[str] = set()
        self._dept_names: dict[str, str] = {}
        self._mun_names: dict[str, str] = {}
        self._zone_names: dict[str, str] = {}
        self._stand_names: dict[str, str] = {}
        self._catalogs_loaded = False

    async def _fetch_json(self, client: httpx.AsyncClient, url: str) -> dict | None:
        try:
            r = await client.get(url, headers=_HEADERS, timeout=30)
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            if "json" not in ct:
                log.warning("Expected JSON but got %s from %s", ct, url)
                return None
            return r.json()
        except Exception as exc:
            log.error("Failed to fetch %s: %s", url, exc)
            return None

    async def _load_catalogs(self, client: httpx.AsyncClient) -> bool:
        """Load name maps from departments/corporations/tree catalogs."""
        depts = await self._fetch_json(client, f"{_CATALOG_BASE}/allDepartments.json")
        tree = await self._fetch_json(client, f"{_CATALOG_BASE}/departmentsTree.json")

        if not depts or not tree:
            return False

        for d in (depts.get("data", {}).get("allDepartments", {}).get("nodes") or []):
            code = _zfill(d.get("idDepartmentCode"), 2)
            self._dept_names[code] = str(d.get("departmentName") or code)

        for edge in (tree.get("data", {}).get("departmentsTree", {}).get("edges") or []):
            dep = _zfill(edge.get("node", {}).get("idDepartmentCode"), 2)
            for m in (edge.get("node", {}).get("municipalities") or []):
                mun = _zfill(m.get("municipalityCode"), 3)
                self._mun_names[f"{dep}|{mun}"] = str(m.get("municipalityName") or mun)
                for z in (m.get("zones") or []):
                    zone2 = _zfill(z.get("idZoneCode"), 2)
                    self._zone_names[f"{dep}|{mun}|{zone2}"] = str(z.get("zoneName") or zone2)
                    for s in (z.get("stands") or []):
                        stand2 = _zfill(s.get("standCode"), 2)
                        self._stand_names[f"{dep}|{mun}|{zone2}|{stand2}"] = str(
                            s.get("standName") or stand2
                        )

        self._catalogs_loaded = True
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
            # Load name catalogs on first call or if not loaded yet
            if not self._catalogs_loaded:
                if not await self._load_catalogs(client):
                    log.warning("Catalogs not available yet — data not published")
                    return stats

            # Fetch transmission catalog
            tx = await self._fetch_json(client, f"{_CATALOG_BASE}/allTransmissionCodes.json")
            if not tx:
                log.warning("allTransmissionCodes.json not available yet")
                return stats

            nodes: list[dict] = []
            tx_data = tx.get("data") or {}
            for key in ("status3", "status11"):
                block = tx_data.get(key)
                if block and isinstance(block, dict):
                    nodes.extend(block.get("nodes") or [])

            # Filter: target department only (default=05 Antioquia) + SEN and CAM only
            filtered = []
            for row in nodes:
                dep = _zfill(row.get("idDepartmentCode"), 2)
                if DEPT_CODE not in ("ALL", "") and dep != DEPT_CODE:
                    continue
                corp3 = _zfill(row.get("idCorporationCode"), 3)
                acronym = _CORP_ACRONYMS.get(corp3)
                if acronym not in (CORP_SEN, CORP_CAM):
                    continue
                expected = str(row.get("expectedName") or "").strip()
                if not expected:
                    continue
                filtered.append((row, dep, corp3, acronym, expected))

            stats["fetched"] = len(filtered)
            if not filtered:
                log.info("No E14s available for dept=%s yet", DEPT_CODE)
                return stats

            E14_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

            for row, dep, corp3, acronym, expected in filtered:
                mun = _zfill(row.get("municipalityCode"), 3)
                zone2 = _zfill(row.get("idZoneCode"), 2)
                zone3 = _zfill(row.get("idZoneCode"), 3)
                stand2 = _zfill(row.get("standCode"), 2)
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
                    f"/{acronym}/{expected}?uuid={uuid.uuid4()}"
                )

                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    r = await client.get(pdf_url, headers=_HEADERS, timeout=60)
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
