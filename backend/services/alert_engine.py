"""Alert engine - detects vote discrepancies and low OCR confidence."""
from datetime import datetime
from backend import database as db
from backend.config import ALERT_DISCREPANCY_PCT, ALERT_LOW_CONFIDENCE
from backend.services.event_bus import event_bus


async def evaluate_mesa(municipio_cod: str, zona_cod: str, puesto_cod: str, mesa: int):
    """Evaluate a mesa for alerts after OCR processing."""
    conn = await db.get_db()

    # Get both SEN and CAM results for this mesa
    results = await conn.execute_fetchall("""
        SELECT corporacion, ph_total_votos, ocr_confidence, status
        FROM e14_results
        WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ? AND mesa = ?
            AND (status = 'processed' OR status = 'corrected')
    """, (municipio_cod, zona_cod, puesto_cod, mesa))

    sen_result = None
    cam_result = None
    for r in results:
        row = dict(r)
        if row["corporacion"] == "SEN":
            sen_result = row
        elif row["corporacion"] == "CAM":
            cam_result = row

    # Check low confidence at mesa level.
    low_conf_rows = [
        r for r in [sen_result, cam_result]
        if r and r["ocr_confidence"] is not None and r["ocr_confidence"] < ALERT_LOW_CONFIDENCE
    ]
    if low_conf_rows:
        worst = min(low_conf_rows, key=lambda x: x["ocr_confidence"])
        alert_data = {
            "municipio_cod": municipio_cod,
            "zona_cod": zona_cod,
            "puesto_cod": puesto_cod,
            "mesa": mesa,
            "alert_type": "low_confidence",
            "severity": "warning",
            "description": (
                f"Baja confianza OCR ({worst['ocr_confidence']:.0f}%) "
                f"en {worst['corporacion']}"
            ),
            "created_at": datetime.now().isoformat(),
        }
        await db.upsert_alert(alert_data)
        await event_bus.publish("alert_created", {
            "municipio_cod": municipio_cod,
            "zona_cod": zona_cod,
            "puesto_cod": puesto_cod,
            "mesa": mesa,
            "type": "low_confidence",
            "severity": "warning",
        })
    else:
        await conn.execute(
            """UPDATE alerts SET is_resolved = 1, resolved_at = ?
               WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
                 AND mesa = ? AND alert_type = 'low_confidence' AND is_resolved = 0""",
            (datetime.now().isoformat(), municipio_cod, zona_cod, puesto_cod, mesa),
        )
        await conn.commit()

    # Check vote discrepancy only when both SEN and CAM exist
    if sen_result and cam_result:
        sen_votes = sen_result.get("ph_total_votos")
        cam_votes = cam_result.get("ph_total_votos")

        if sen_votes is not None and cam_votes is not None:
            max_votes = max(sen_votes, cam_votes, 1)
            diff_pct = abs(sen_votes - cam_votes) / max_votes * 100

            if diff_pct >= ALERT_DISCREPANCY_PCT:
                alert_data = {
                    "municipio_cod": municipio_cod,
                    "zona_cod": zona_cod,
                    "puesto_cod": puesto_cod,
                    "mesa": mesa,
                    "alert_type": "vote_discrepancy",
                    "severity": "danger",
                    "description": (
                        f"Diferencia {diff_pct:.1f}% entre PH Senado ({sen_votes}) "
                        f"y Camara ({cam_votes})"
                    ),
                    "sen_ph_votes": sen_votes,
                    "cam_ph_votes": cam_votes,
                    "discrepancy_pct": round(diff_pct, 1),
                    "created_at": datetime.now().isoformat(),
                }
                await db.upsert_alert(alert_data)
                await event_bus.publish("alert_created", {
                    "municipio_cod": municipio_cod, "zona_cod": zona_cod,
                    "puesto_cod": puesto_cod, "mesa": mesa,
                    "type": "vote_discrepancy", "severity": "danger",
                    "pct": round(diff_pct, 1),
                })
                return True  # Alert created
            else:
                # Resolve any existing alert if now below threshold
                await conn.execute("""
                    UPDATE alerts SET is_resolved = 1, resolved_at = ?
                    WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
                        AND mesa = ? AND alert_type = 'vote_discrepancy' AND is_resolved = 0
                """, (datetime.now().isoformat(),
                      municipio_cod, zona_cod, puesto_cod, mesa))
                await conn.commit()

    return False
