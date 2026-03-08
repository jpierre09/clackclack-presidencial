"""Remote poller for Registraduria transmission catalogs.

The source endpoint may be rate-limited or protected depending on election day infrastructure.
This service is optional and disabled by default.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from backend import database as db
from backend.config import (
    CORP_CAM,
    CORP_SEN,
    DEPT_CODE,
    E14_DOWNLOADS_DIR,
    POLL_INTERVAL,
    REGISTRADURIA_CATALOGS_URL,
    REGISTRADURIA_BASE_URL,
)
from backend.services.downloader import DEFAULT_HEADERS, download_pdf
from backend.services.event_bus import event_bus
from backend.services.local_ingest import ingest_file


CATALOG_URL = f"{REGISTRADURIA_CATALOGS_URL}/allTransmissionCodes.json"


class RemotePoller:
    def __init__(self):
        self._known_keys: set[str] = set()

    @staticmethod
    def _normalize_corp(raw: str | None) -> str | None:
        if not raw:
            return None
        value = raw.upper()
        if "SEN" in value:
            return CORP_SEN
        if "CAM" in value:
            return CORP_CAM
        return None

    @staticmethod
    def _extract_candidates(payload: Any) -> list[dict]:
        candidates: list[dict] = []

        def walk(node: Any):
            if isinstance(node, dict):
                keys = {k.lower(): k for k in node.keys()}
                maybe_url = None
                for key in ("url", "pdf", "pdf_url", "archivo", "file", "path", "href"):
                    if key in keys:
                        maybe_url = str(node[keys[key]])
                        break

                dep = (
                    node.get(keys.get("departamento"))
                    or node.get(keys.get("departamento_cod"))
                    or node.get(keys.get("codigodepartamento"))
                    or node.get(keys.get("dd"))
                    or node.get(keys.get("dep"))
                )
                mun = (
                    node.get(keys.get("municipio_cod"))
                    or node.get(keys.get("codigomunicipio"))
                    or node.get(keys.get("mm"))
                    or node.get(keys.get("mun"))
                )
                zona = node.get(keys.get("zona")) or node.get(keys.get("zz"))
                puesto = node.get(keys.get("puesto")) or node.get(keys.get("pp"))
                mesa = node.get(keys.get("mesa"))
                corp = (
                    node.get(keys.get("corporacion"))
                    or node.get(keys.get("acronimo"))
                    or node.get(keys.get("corp"))
                    or node.get(keys.get("corp_alias"))
                )

                if maybe_url and dep is not None and mun is not None and zona is not None and puesto is not None and mesa is not None:
                    candidates.append(
                        {
                            "url": maybe_url,
                            "departamento_cod": str(dep).zfill(2),
                            "municipio_cod": str(mun).zfill(3),
                            "zona_cod": str(zona).zfill(2),
                            "puesto_cod": str(puesto).zfill(2),
                            "mesa": int(str(mesa).strip()),
                            "corporacion": str(corp or ""),
                        }
                    )

                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)

        # Deduplicate extracted rows
        uniq = {}
        for candidate in candidates:
            key = (
                candidate["departamento_cod"],
                candidate["municipio_cod"],
                candidate["zona_cod"],
                candidate["puesto_cod"],
                candidate["mesa"],
                candidate["corporacion"],
                candidate["url"],
            )
            uniq[key] = candidate
        return list(uniq.values())

    async def poll_once(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
                response = await client.get(CATALOG_URL)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            await event_bus.publish("remote_poll_error", {"error": str(exc)})
            return {"fetched": 0, "downloaded": 0, "processed": 0, "errors": 1}

        candidates = self._extract_candidates(payload)
        filtered = [
            c for c in candidates
            if c["departamento_cod"] == DEPT_CODE and self._normalize_corp(c["corporacion"]) in {CORP_SEN, CORP_CAM}
        ]

        downloaded = 0
        processed = 0
        errors = 0

        for row in filtered:
            corp = self._normalize_corp(row["corporacion"]) or "UNK"
            if corp not in {CORP_SEN, CORP_CAM}:
                continue

            url = row["url"]
            if url.startswith("/"):
                url = f"{REGISTRADURIA_BASE_URL}{url}"
            elif not url.startswith("http"):
                url = f"{REGISTRADURIA_BASE_URL.rstrip('/')}/{url.lstrip('/')}"

            unique_key = (
                f"{row['municipio_cod']}-{row['zona_cod']}-{row['puesto_cod']}-"
                f"{row['mesa']}-{corp}-{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}"
            )
            if unique_key in self._known_keys:
                continue

            target = (
                E14_DOWNLOADS_DIR
                / f"{DEPT_CODE}-ANTIOQUIA"
                / f"{row['municipio_cod']}-MUNICIPIO"
                / f"{row['zona_cod']}-Zona {row['zona_cod']}"
                / f"{row['puesto_cod']}-PUESTO"
                / f"MESA_{row['mesa']:03d}_{corp}_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}.pdf"
            )

            ok = await download_pdf(url, target)
            if not ok:
                errors += 1
                continue

            downloaded += 1
            self._known_keys.add(unique_key)

            try:
                processed_flag, _ = await ingest_file(target)
                if processed_flag:
                    processed += 1
            except Exception:
                errors += 1

        stats = {
            "fetched": len(filtered),
            "downloaded": downloaded,
            "processed": processed,
            "errors": errors,
        }
        await event_bus.publish("remote_poll_complete", stats)
        return stats

    async def loop(self, stop_event: asyncio.Event):
        while not stop_event.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                continue


remote_poller = RemotePoller()
