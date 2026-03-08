"""Alert management endpoints."""
from datetime import datetime
from fastapi import APIRouter
from backend import database as db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
async def get_alerts(municipio: str = None, resolved: bool = False):
    return await db.get_alerts(municipio_cod=municipio, resolved=resolved)


@router.put("/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    conn = await db.get_db()
    await conn.execute(
        "UPDATE alerts SET is_resolved = 1, resolved_at = ? WHERE id = ?",
        (datetime.now().isoformat(), alert_id)
    )
    await conn.commit()
    return {"status": "resolved", "id": alert_id}
