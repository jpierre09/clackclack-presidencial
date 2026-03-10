"""Alert management endpoints."""
import asyncio
import time
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import database as db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Simple TTL cache for review-items (30s)
_review_cache: dict[str, tuple[float, object]] = {}
_review_locks: dict[str, asyncio.Lock] = {}


def _review_lock(key: str) -> asyncio.Lock:
    if key not in _review_locks:
        _review_locks[key] = asyncio.Lock()
    return _review_locks[key]


async def _cached_review(key: str, ttl: int, fn):
    if key in _review_cache:
        ts, val = _review_cache[key]
        if time.monotonic() - ts < ttl:
            return val
    async with _review_lock(key):
        if key in _review_cache:
            ts, val = _review_cache[key]
            if time.monotonic() - ts < ttl:
                return val
        val = await fn()
        _review_cache[key] = (time.monotonic(), val)
        return val


class AlertReviewRequest(BaseModel):
    decision: Literal["real_alert", "false_alert"]
    reviewed_by: str = "dashboard"


@router.get("")
async def get_alerts(municipio: str = None, resolved: bool = False):
    return await db.get_alerts(municipio_cod=municipio, resolved=resolved)


@router.get("/review-items")
async def get_alert_review_items(
    municipio: str = None,
    reviewed: bool = False,
    limit: int = 200,
    offset: int = 0,
):
    cache_key = f"review:{reviewed}:{municipio or ''}:{limit}:{offset}"
    return await _cached_review(
        cache_key,
        30,
        lambda: db.get_alert_review_items(
            municipio_cod=municipio, reviewed=reviewed, limit=limit, offset=offset
        ),
    )


@router.put("/{alert_id}/review")
async def review_alert(alert_id: int, payload: AlertReviewRequest):
    ok = await db.review_alert(alert_id, payload.decision, payload.reviewed_by or "dashboard")
    if not ok:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    # Bust review-items cache so the next load sees updated data immediately
    _review_cache.clear()
    return {"status": payload.decision, "id": alert_id}


@router.put("/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    conn = await db.get_db()
    await conn.execute(
        "UPDATE alerts SET is_resolved = 1, resolved_at = ? WHERE id = ?",
        (datetime.now().isoformat(), alert_id)
    )
    await conn.commit()
    return {"status": "resolved", "id": alert_id}
