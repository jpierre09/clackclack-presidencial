"""Alert engine - detects vote discrepancies after manual validation."""
from datetime import datetime
from backend import database as db
from backend.config import ALERT_DISCREPANCY_PCT
from backend.services.event_bus import event_bus


async def evaluate_mesa(municipio_cod: str, zona_cod: str, puesto_cod: str, mesa: int):
    """Evaluate a mesa for discrepancy alert. Called after manual validation."""
    conn = await db.get_db()

    # Get both SEN and CAM results for this mesa (validated or corrected)
    results = await conn.execute_fetchall(
        """
        SELECT r.corporacion, r.ph_total_votos
        FROM e14_results r
        JOIN manual_validations mv
            ON mv.municipio_cod = r.municipio_cod
            AND mv.zona_cod = r.zona_cod
            AND mv.puesto_cod = r.puesto_cod
            AND mv.mesa = r.mesa
            AND mv.corporacion = r.corporacion
        WHERE r.municipio_cod = ? AND r.zona_cod = ? AND r.puesto_cod = ?
          AND r.mesa = ?
          AND r.status IN ('processed', 'corrected')
        """,
        (municipio_cod, zona_cod, puesto_cod, mesa),
    )

    sen_votes = None
    cam_votes = None
    for r in results:
        row = dict(r)
        if row["corporacion"] == "SEN":
            sen_votes = row["ph_total_votos"]
        elif row["corporacion"] == "CAM":
            cam_votes = row["ph_total_votos"]

    # Only check when both SEN and CAM have been validated
    if sen_votes is None or cam_votes is None:
        return False

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
        await event_bus.publish(
            "alert_created",
            {
                "municipio_cod": municipio_cod,
                "zona_cod": zona_cod,
                "puesto_cod": puesto_cod,
                "mesa": mesa,
                "type": "vote_discrepancy",
                "severity": "danger",
                "pct": round(diff_pct, 1),
            },
        )
        return True
    else:
        # Resolve any existing alert if now below threshold
        await conn.execute(
            """
            UPDATE alerts SET is_resolved = 1, resolved_at = ?
            WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
              AND mesa = ? AND alert_type = 'vote_discrepancy' AND is_resolved = 0
            """,
            (datetime.now().isoformat(), municipio_cod, zona_cod, puesto_cod, mesa),
        )
        await conn.commit()

    return False
