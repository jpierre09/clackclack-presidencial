"""Alert management endpoints."""
import asyncio
import secrets
import time
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import database as db
from backend.config import VALIDATE_SETUP_TOKEN

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


class BulkAlertReviewRequest(BaseModel):
    admin_token: str
    decision: Literal["real_alert", "false_alert"]
    reviewed_by: str = "dashboard_bulk"
    municipio: str | None = None


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


@router.get("/review-summary")
async def get_alert_review_summary(municipio: str = None):
    cache_key = f"review-summary:{municipio or ''}"
    return await _cached_review(
        cache_key,
        30,
        lambda: db.get_alert_review_summary(municipio_cod=municipio),
    )


@router.get("/recent-real")
async def recent_real_alerts(limit: int = 10):
    """Last N alerts marked as real_alert with their validated vote values."""
    conn = await db.get_db()
    rows = await conn.execute_fetchall("""
        SELECT a.id, a.municipio_cod, a.zona_cod, a.puesto_cod, a.mesa,
               a.discrepancy_pct, a.reviewed_at, a.reviewed_by,
               p.municipio, p.nombre AS puesto_nombre,
               COALESCE(mv.corrected_ph_votes, pres_r.ph_total_votos) AS pres_validated,
               mv.action AS pres_action
        FROM alerts a
        LEFT JOIN puestos p ON p.municipio_cod=a.municipio_cod
            AND p.zona_cod=a.zona_cod AND p.puesto_cod=a.puesto_cod
        LEFT JOIN e14_results pres_r ON pres_r.municipio_cod=a.municipio_cod
            AND pres_r.zona_cod=a.zona_cod AND pres_r.puesto_cod=a.puesto_cod
            AND pres_r.mesa=a.mesa AND pres_r.corporacion='PRES'
        LEFT JOIN manual_validations mv ON mv.municipio_cod=a.municipio_cod
            AND mv.zona_cod=a.zona_cod AND mv.puesto_cod=a.puesto_cod
            AND mv.mesa=a.mesa AND mv.corporacion='PRES'
        WHERE a.review_decision='real_alert'
        ORDER BY a.reviewed_at DESC
        LIMIT ?
    """, (limit,))
    return [dict(r) for r in rows]


@router.post("/review-bulk")
async def bulk_review_alerts(payload: BulkAlertReviewRequest):
    if not VALIDATE_SETUP_TOKEN:
        raise HTTPException(status_code=503, detail="VALIDATE_SETUP_TOKEN not configured")
    if not secrets.compare_digest(payload.admin_token, VALIDATE_SETUP_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")

    result = await db.bulk_review_pending_alerts(
        decision=payload.decision,
        reviewed_by=payload.reviewed_by or "dashboard_bulk",
        municipio_cod=payload.municipio,
    )
    _review_cache.clear()
    return result


class MarkNoveltyRequest(BaseModel):
    note: str
    reviewed_by: str = "dashboard"


@router.put("/{alert_id}/mark-novelty")
async def mark_novelty(alert_id: int, payload: MarkNoveltyRequest):
    """Mark a PRES mesa as novelty (blue) from the review panel."""
    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        "SELECT municipio_cod, zona_cod, puesto_cod, mesa FROM alerts WHERE id = ?", (alert_id,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    r = dict(rows[0])
    from datetime import datetime
    now = datetime.now().isoformat()
    await conn.execute("""
        INSERT INTO manual_validations
            (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
             action, corrected_ph_votes, novelty_note, validated_by, validated_at)
        VALUES (?, ?, ?, ?, 'PRES', 'novelty', NULL, ?, ?, ?)
        ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
        DO UPDATE SET action='novelty', corrected_ph_votes=NULL,
            novelty_note=excluded.novelty_note,
            validated_by=excluded.validated_by, validated_at=excluded.validated_at
    """, (r["municipio_cod"], r["zona_cod"], r["puesto_cod"], r["mesa"],
          payload.note, payload.reviewed_by, now))
    await conn.commit()
    _review_cache.clear()
    return {"status": "ok", "note": payload.note}


@router.put("/{alert_id}/undo-review")
async def undo_review(alert_id: int):
    """Revert a review decision back to pending (review_decision = NULL)."""
    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        "SELECT id FROM alerts WHERE id = ? AND review_decision IS NOT NULL", (alert_id,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Alerta no encontrada o sin decision")
    await conn.execute(
        """UPDATE alerts SET review_decision = NULL, reviewed_at = NULL,
           reviewed_by = NULL, is_resolved = 0, resolved_at = NULL, resolved_by = NULL
           WHERE id = ?""",
        (alert_id,),
    )
    await conn.commit()
    _review_cache.clear()
    return {"status": "reverted", "id": alert_id}


@router.put("/{alert_id}/review")
async def review_alert(alert_id: int, payload: AlertReviewRequest):
    ok = await db.review_alert(alert_id, payload.decision, payload.reviewed_by or "dashboard")
    if not ok:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    # Bust review-items cache so the next load sees updated data immediately
    _review_cache.clear()
    return {"status": payload.decision, "id": alert_id}


class CorrectVotesRequest(BaseModel):
    votes: int
    reviewed_by: str = "dashboard"


@router.put("/{alert_id}/correct-votes")
async def correct_votes(alert_id: int, payload: CorrectVotesRequest):
    """Override the validated total vote count for PRES on a mesa from the review panel."""
    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        "SELECT municipio_cod, zona_cod, puesto_cod, mesa FROM alerts WHERE id = ?",
        (alert_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    r = dict(rows[0])
    from datetime import datetime
    now = datetime.now().isoformat()

    await conn.execute("""
        INSERT INTO manual_validations
            (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
             action, corrected_ph_votes, validated_by, validated_at)
        VALUES (?, ?, ?, ?, 'PRES', 'corrected', ?, ?, ?)
        ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
        DO UPDATE SET
            action = 'corrected',
            corrected_ph_votes = excluded.corrected_ph_votes,
            validated_by = excluded.validated_by,
            validated_at = excluded.validated_at
    """, (r["municipio_cod"], r["zona_cod"], r["puesto_cod"], r["mesa"],
          payload.votes, payload.reviewed_by, now))

    await conn.execute("""
        UPDATE e14_results SET ph_total_votos = ?, status = 'corrected'
        WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ? AND mesa = ? AND corporacion = 'PRES'
    """, (payload.votes, r["municipio_cod"], r["zona_cod"], r["puesto_cod"], r["mesa"]))

    await conn.commit()

    from backend.services import alert_engine
    await alert_engine.evaluate_mesa(r["municipio_cod"], r["zona_cod"], r["puesto_cod"], r["mesa"])

    _review_cache.clear()
    return {"status": "ok", "votes": payload.votes}


@router.put("/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    conn = await db.get_db()
    await conn.execute(
        "UPDATE alerts SET is_resolved = 1, resolved_at = ? WHERE id = ?",
        (datetime.now().isoformat(), alert_id)
    )
    await conn.commit()
    return {"status": "resolved", "id": alert_id}
