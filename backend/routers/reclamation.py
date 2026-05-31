"""Reclamation document generation endpoints."""
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from backend import database as db
from backend.models import ReclamationRequest
from backend.services import docx_generator

router = APIRouter(prefix="/api/reclamation", tags=["reclamation"])


@router.post("/generate")
async def generate_reclamation(req: ReclamationRequest):
    """Generate reclamation DOCX(s) for alerts at the specified level."""
    alerts = await db.get_alerts_for_reclamation(
        req.level, req.municipio_cod, req.zona_cod, req.puesto_cod, req.mesa
    )

    if not alerts:
        return {"error": "No alerts found for the specified location"}

    user_name = req.user_name or await db.get_setting("user_name", "")
    user_cc = req.user_cc or await db.get_setting("user_cc", "")

    if len(alerts) == 1 and req.level == "mesa":
        # Single mesa - return single DOCX
        comision = await db.get_comision_for_mesa(
            alerts[0]["municipio_cod"], alerts[0]["zona_cod"],
            alerts[0]["puesto_cod"], alerts[0]["mesa"]
        )
        buffer = docx_generator.generate_single(alerts[0], comision, user_name, user_cc)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename=Reclamacion_Departamental_Mesa_{alerts[0]['mesa']}.docx"}
        )
    else:
        # Multiple alerts - return ZIP
        buffer = await docx_generator.generate_batch(alerts, user_name, user_cc)
        mun = alerts[0].get("municipio", "Antioquia")
        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=Reclamaciones_{mun}.zip"}
        )


@router.post("/generate-departamental")
async def generate_departamental_reclamations():
    """Generate a ZIP with reclamation DOCXs for all unresolved discrepancy alerts."""
    alerts = await db.get_all_alerts_for_reclamation()
    if not alerts:
        return {"error": "No active discrepancy alerts found"}

    buffer = await docx_generator.generate_batch(alerts)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="Reclamaciones_Departamentales_{stamp}.zip"'
            )
        },
    )
