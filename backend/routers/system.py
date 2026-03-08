"""Operational endpoints for scans/poller health."""
from fastapi import APIRouter

from backend.config import (
    AUTO_SEED_DEMO,
    DEMO_EXPO_MODE,
    ENABLE_LOCAL_INGEST,
    ENABLE_REMOTE_POLLER,
    SERVE_FRONTEND,
)
from backend.services.event_bus import event_bus
from backend.services.demo_data import clear_demo_data, seed_demo_data

router = APIRouter(prefix="/api/system", tags=["system"])


@router.post("/rescan")
async def trigger_rescan(limit: int | None = None):
    if not ENABLE_LOCAL_INGEST:
        return {
            "status": "disabled",
            "scan": {"enabled": False, "reason": "local_ingest_disabled"},
        }

    from backend.services.local_ingest import scan_local_downloads

    stats = await scan_local_downloads(limit=limit)
    return {"status": "ok", "scan": stats}


@router.post("/poll-once")
async def remote_poll_once():
    if not ENABLE_REMOTE_POLLER:
        return {
            "status": "disabled",
            "poll": {"enabled": False, "reason": "remote_poller_disabled"},
        }

    from backend.services.remote_poller import remote_poller

    stats = await remote_poller.poll_once()
    return {"status": "ok", "poll": stats}


@router.get("/status")
async def status():
    return {
        "subscribers": event_bus.subscriber_count(),
        "mode": {
            "demo_expo": DEMO_EXPO_MODE,
            "frontend_served": SERVE_FRONTEND,
            "auto_seed_demo": AUTO_SEED_DEMO,
            "local_ingest_enabled": ENABLE_LOCAL_INGEST,
            "remote_poller_enabled": ENABLE_REMOTE_POLLER,
        },
    }


@router.post("/demo-seed")
async def demo_seed(total_mesas: int = 180, clear_first: bool = True, seed: int = 20260304):
    stats = await seed_demo_data(total_mesas=total_mesas, clear_first=clear_first, seed=seed)
    return {"status": "ok", "demo": stats}


@router.delete("/demo-clear")
async def demo_clear():
    stats = await clear_demo_data()
    return {"status": "ok", "demo": stats}
