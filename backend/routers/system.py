"""Operational endpoints for scans/poller health."""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.config import (
    DEPT_CODE,
    E14_DOWNLOADS_DIR,
    ENABLE_LOCAL_INGEST,
    ENABLE_REMOTE_POLLER,
    SERVE_FRONTEND,
    SFTP_HOST,
    SFTP_POLL_INTERVAL,
    SFTP_READY,
)
from backend.services.event_bus import event_bus

router = APIRouter(prefix="/api/system", tags=["system"])


@router.post("/rescan")
async def trigger_rescan(limit: int | None = None):
    if not ENABLE_LOCAL_INGEST:
        return {"status": "disabled", "reason": "local_ingest_disabled"}

    from backend.services.local_ingest import scan_local_downloads

    stats = await scan_local_downloads(limit=limit)
    return {"status": "ok", "scan": stats}


@router.post("/poll-once")
async def remote_poll_once():
    if not ENABLE_REMOTE_POLLER:
        return {"status": "disabled", "reason": "remote_poller_disabled"}

    from backend.services.remote_poller import remote_poller

    stats = await remote_poller.poll_once()
    return {"status": "ok", "poll": stats}


@router.post("/sftp-sync")
async def sftp_sync():
    """Manually trigger an SFTP download cycle."""
    if not SFTP_READY:
        return {
            "status": "waiting",
            "reason": "SFTP credentials not configured. Set SFTP_HOST, SFTP_USER, SFTP_PASS.",
        }

    from backend.services.sftp_downloader import download_new_pdfs
    from backend.services.local_ingest import ingest_file
    from pathlib import Path

    new_files = await download_new_pdfs()
    processed = 0
    for meta in new_files:
        ok, _ = await ingest_file(Path(meta["local_path"]))
        if ok:
            processed += 1

    return {"status": "ok", "downloaded": len(new_files), "processed": processed}


@router.post("/upload-e14")
async def upload_e14(
    file: UploadFile = File(...),
    dept_code: str = Form(...),   # e.g. "29"
    mun_code: str = Form(...),    # e.g. "001"
    zona_code: str = Form(...),   # e.g. "01"
    puesto_code: str = Form(...), # e.g. "01"
    mesa: int = Form(...),        # e.g. 3
    corp: str = Form(...),        # "SEN" | "CAM"
):
    """Accept a PDF upload and ingest it as if it came from SFTP."""
    from pathlib import Path
    from backend.services.local_ingest import ingest_file

    corp = corp.upper()
    if corp not in ("SEN", "CAM"):
        raise HTTPException(status_code=400, detail="corp must be SEN or CAM")

    dest_dir = (
        E14_DOWNLOADS_DIR
        / f"{dept_code}-UPLOAD"
        / f"{mun_code}-MUN"
        / f"{zona_code}-Zona {zona_code}"
        / f"{puesto_code}-PUESTO"
    )
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Keep original filename or build a canonical one
    original_name = file.filename or f"MESA_{mesa:03d}_{corp}_upload.pdf"
    if not original_name.upper().startswith("MESA_"):
        original_name = f"MESA_{mesa:03d}_{corp}_{original_name}"

    dest_path = dest_dir / original_name
    content = await file.read()
    dest_path.write_bytes(content)

    ok, reason = await ingest_file(dest_path)
    return {
        "status": "ok" if ok else "skipped",
        "reason": reason,
        "path": str(dest_path.relative_to(E14_DOWNLOADS_DIR)),
        "size_kb": round(len(content) / 1024, 1),
    }


@router.get("/ocr-errors")
async def ocr_errors():
    """Show top OCR error messages grouped by type."""
    from backend import database as db
    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT corporacion, error_message, COUNT(*) as n,
                  MAX(processed_at) as last_at
           FROM e14_results WHERE status='error'
           GROUP BY corporacion, error_message
           ORDER BY n DESC LIMIT 20"""
    )
    return [dict(r) for r in rows]


@router.post("/reset-key-state")
async def reset_key_state():
    """Clear the Claude API key exhaustion state so rotation resets."""
    from backend.services.claude_ocr import _BASE
    state_file = _BASE / "ClaudeKeyState.json"
    if state_file.exists():
        state_file.unlink()
    return {"status": "ok", "message": "ClaudeKeyState.json eliminado — rotación de claves reseteada"}


@router.post("/retry-errors")
async def retry_errors(limit: int = 20):
    """Delete error-status results so they can be re-processed on next rescan."""
    from backend import database as db
    conn = await db.get_db()
    await conn.execute(
        "DELETE FROM e14_results WHERE status='error' LIMIT ?", (limit,)
    )
    await conn.commit()
    result = await conn.execute_fetchall("SELECT changes() as n")
    return {"deleted": result[0]["n"] if result else 0}


@router.get("/status")
async def status():
    return {
        "subscribers": event_bus.subscriber_count(),
        "mode": {
            "frontend_served": SERVE_FRONTEND,
            "local_ingest_enabled": ENABLE_LOCAL_INGEST,
            "remote_poller_enabled": ENABLE_REMOTE_POLLER,
            "sftp_ready": SFTP_READY,
            "sftp_host": SFTP_HOST or None,
            "sftp_poll_interval_s": SFTP_POLL_INTERVAL,
            "dept_code_filter": DEPT_CODE,
        },
    }
