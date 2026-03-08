"""Operational endpoints for scans/poller health."""
from fastapi import APIRouter

from backend.config import (
    ENABLE_LOCAL_INGEST,
    ENABLE_REMOTE_POLLER,
    SERVE_FRONTEND,
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


@router.get("/status")
async def status():
    return {
        "subscribers": event_bus.subscriber_count(),
        "mode": {
            "frontend_served": SERVE_FRONTEND,
            "local_ingest_enabled": ENABLE_LOCAL_INGEST,
            "remote_poller_enabled": ENABLE_REMOTE_POLLER,
            "sftp_ready": SFTP_READY,
        },
    }
