"""Alert engine — detects OCR arithmetic issues for presidential E-14 mesas."""
from datetime import datetime
from backend import database as db
from backend.services.event_bus import event_bus


async def evaluate_mesa(municipio_cod: str, zona_cod: str, puesto_cod: str, mesa: int):
    """Evaluate a PRES mesa for data-quality alert after manual validation."""
    conn = await db.get_db()

    rows = await conn.execute_fetchall(
        """
        SELECT r.ph_total_votos, r.votos_urna, r.all_sections_json, r.ocr_confidence
        FROM e14_results r
        WHERE r.municipio_cod = ? AND r.zona_cod = ? AND r.puesto_cod = ?
          AND r.mesa = ? AND r.corporacion = 'PRES'
          AND r.status IN ('processed', 'corrected')
        LIMIT 1
        """,
        (municipio_cod, zona_cod, puesto_cod, mesa),
    )

    if not rows:
        return False

    row = dict(rows[0])
    total_candidatos = row.get("ph_total_votos") or 0
    votos_urna = row.get("votos_urna") or 0

    # Flag when sum of all candidate votes exceeds total votes in ballot box
    if votos_urna > 0 and total_candidatos > votos_urna:
        over = total_candidatos - votos_urna
        alert_data = {
            "municipio_cod": municipio_cod,
            "zona_cod": zona_cod,
            "puesto_cod": puesto_cod,
            "mesa": mesa,
            "alert_type": "vote_sum_exceeds_urna",
            "severity": "danger",
            "description": (
                f"Suma candidatos ({total_candidatos}) supera votos en urna "
                f"({votos_urna}) por {over}"
            ),
            "discrepancy_pct": round(over / votos_urna * 100, 1),
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
                "type": "vote_sum_exceeds_urna",
                "severity": "danger",
            },
        )
        return True

    # Resolve any existing alert if numbers now look consistent
    await conn.execute(
        """
        UPDATE alerts SET is_resolved = 1, resolved_at = ?
        WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
          AND mesa = ? AND alert_type = 'vote_sum_exceeds_urna' AND is_resolved = 0
        """,
        (datetime.now().isoformat(), municipio_cod, zona_cod, puesto_cod, mesa),
    )
    await conn.commit()
    return False
