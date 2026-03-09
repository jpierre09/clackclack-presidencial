"""Local E14 discovery and OCR ingestion pipeline."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path

from backend import database as db
from backend.config import DEPT_CODE, E14_DOWNLOADS_DIR, LOCAL_SCAN_INTERVAL
from backend.services import ocr_processor
from backend.services.event_bus import event_bus


FILE_RE = re.compile(r"^MESA_(\d{1,3})_(SEN|CAM)_.*\.pdf$", re.IGNORECASE)
CODE_RE = re.compile(r"^(\d{2,3})-")
_scan_lock = asyncio.Lock()
_OCR_SEM = asyncio.Semaphore(8)  # max concurrent OCR jobs



def _parse_code(part: str, size: int) -> str | None:
    match = CODE_RE.match(part)
    if not match:
        return None
    return match.group(1).zfill(size)



def parse_e14_metadata(pdf_path: Path) -> dict | None:
    """Parse path metadata from a local E14 file.

    Expected structure:
    e14_downloads/{dep}/{mun}/{zona}/{puesto}/MESA_001_SEN_x.pdf
    """
    try:
        rel = pdf_path.resolve().relative_to(E14_DOWNLOADS_DIR.resolve())
    except ValueError:
        return None

    parts = rel.parts
    if len(parts) < 5:
        return None

    dep_part, mun_part, zona_part, puesto_part = parts[0], parts[1], parts[2], parts[3]
    filename = parts[-1]

    dep_code = _parse_code(dep_part, 2)
    mun_code = _parse_code(mun_part, 3)
    zona_code = _parse_code(zona_part, 2)
    puesto_code = _parse_code(puesto_part, 2)
    file_match = FILE_RE.match(filename)

    if not dep_code:
        return None
    if DEPT_CODE not in ("ALL", "") and dep_code != DEPT_CODE:
        return None
    if not mun_code or not zona_code or not puesto_code or not file_match:
        return None

    mesa = int(file_match.group(1))
    corporacion = file_match.group(2).upper()

    return {
        "municipio_cod": mun_code,
        "zona_cod": zona_code,
        "puesto_cod": puesto_code,
        "mesa": mesa,
        "corporacion": corporacion,
        "filename": filename,
        "filepath": str(pdf_path.resolve()).replace("\\", "/"),
        "downloaded_at": datetime.now().isoformat(),
        "file_size": pdf_path.stat().st_size,
        "full_path": str(pdf_path.resolve()),
    }


async def _has_processed_result(meta: dict) -> bool:
    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT status FROM e14_results
           WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
             AND mesa = ? AND corporacion = ?
           LIMIT 1""",
        (
            meta["municipio_cod"],
            meta["zona_cod"],
            meta["puesto_cod"],
            meta["mesa"],
            meta["corporacion"],
        ),
    )
    if not rows:
        return False
    return rows[0]["status"] in {"processed", "corrected", "not_digitized"}


async def ingest_file(pdf_path: Path) -> tuple[bool, str]:
    """Ingest one local PDF. Returns (processed, reason)."""
    meta = parse_e14_metadata(pdf_path)
    if not meta:
        return False, "invalid_path"

    download_id = await db.insert_download(meta)

    if await _has_processed_result(meta):
        return False, "already_processed"

    await ocr_processor.process_e14(
        download_id=download_id,
        filepath=meta["full_path"],
        municipio_cod=meta["municipio_cod"],
        zona_cod=meta["zona_cod"],
        puesto_cod=meta["puesto_cod"],
        mesa=meta["mesa"],
        corporacion=meta["corporacion"],
    )
    return True, "processed"


async def scan_local_downloads(limit: int | None = None) -> dict:
    """Scan local e14_downloads folder and process new Antioquia PDFs."""
    if _scan_lock.locked():
        return {
            "discovered": 0,
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "status": "already_running",
        }

    if not E14_DOWNLOADS_DIR.exists():
        return {"discovered": 0, "processed": 0, "skipped": 0, "errors": 0}

    async with _scan_lock:
        pdf_files = sorted(E14_DOWNLOADS_DIR.rglob("*.pdf"))
        if limit is not None:
            pdf_files = pdf_files[:limit]
        stats = {"discovered": len(pdf_files), "processed": 0, "skipped": 0, "errors": 0}

        async def _process_one(file_path):
            async with _OCR_SEM:
                try:
                    processed, reason = await ingest_file(file_path)
                    if processed:
                        stats["processed"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception:
                    stats["errors"] += 1

        await asyncio.gather(*[_process_one(p) for p in pdf_files])
        await event_bus.publish("scan_complete", stats)
        return stats


async def local_watch_loop(stop_event: asyncio.Event):
    """Background loop to keep scanning for new local files."""
    while not stop_event.is_set():
        try:
            await scan_local_downloads()
        except Exception as exc:
            await event_bus.publish("scan_error", {"error": str(exc)})

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=LOCAL_SCAN_INTERVAL)
        except asyncio.TimeoutError:
            continue
