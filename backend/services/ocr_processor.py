"""OCR processor - wraps Claude Vision API for async E-14 processing."""
import json
import asyncio
from datetime import datetime

from backend.config import (
    CLAUDE_MAX_PAGES_SEN, CLAUDE_MAX_PAGES_CAM,
    CLAUDE_SEN_PACTO_PAGE, CLAUDE_CAM_PACTO_PAGE,
    PH_PATTERNS,
)
from backend import database as db
from backend.services.event_bus import event_bus
from backend.services.claude_ocr import process_e14_pdf, normalize_result, validate_result


def _pages_for(corporacion: str) -> tuple[int, int]:
    """Return (start_page 0-indexed, max_pages) for the given corporacion."""
    if corporacion.upper() in ("SEN", "SENADO"):
        # Read only the Pacto page (e.g. page 5 → index 4)
        start = max(0, CLAUDE_SEN_PACTO_PAGE - 1)
        return start, CLAUDE_MAX_PAGES_SEN
    # Camara: if pacto page is known read just that page, else read all 3
    if CLAUDE_CAM_PACTO_PAGE > 0:
        start = max(0, CLAUDE_CAM_PACTO_PAGE - 1)
        return start, 1
    return 0, CLAUDE_MAX_PAGES_CAM


def _find_ph_votes(partidos: list[dict]) -> tuple[int | None, int | None]:
    """Find Pacto Historico votes in normalized result."""
    for p in partidos:
        nombre = (p.get("nombre") or "").upper()
        if any(pattern in nombre for pattern in PH_PATTERNS):
            return p.get("votos_lista"), p.get("total_votos")
    return None, None


async def process_e14(download_id: int, filepath: str,
                       municipio_cod: str, zona_cod: str, puesto_cod: str,
                       mesa: int, corporacion: str):
    """Process a single E-14 PDF through Claude Vision and store results."""
    start_time = datetime.now()

    try:
        loop = asyncio.get_event_loop()
        start_page, max_pages = _pages_for(corporacion)
        raw_result = await loop.run_in_executor(
            None, lambda: process_e14_pdf(filepath, max_pages=max_pages, start_page=start_page)
        )

        # Normalize to flat format
        norm = normalize_result(raw_result)

        partidos = norm.get("partidos", [])
        ph_lista, ph_total = _find_ph_votes(partidos)

        niv = norm.get("nivelacion", {})
        votantes_e11 = niv.get("total_sufragantes_e11")
        votos_urna = niv.get("total_votos_urna")

        validacion = norm.get("_validacion", {})
        nivel_alerta = validacion.get("nivel_alerta", "OK")

        confidence = norm.get("confianza_general", 75)
        meta = norm.get("_meta", {})
        processing_time = meta.get("total_time_s", (datetime.now() - start_time).total_seconds())

        # Build sections in DB-compatible format
        sections = []
        for p in partidos:
            sections.append({
                "tipo": "partido",
                "nombre": p.get("nombre", ""),
                "codigo": p.get("codigo", ""),
                "tipo_lista": p.get("tipo_lista", ""),
                "votos_lista": str(p.get("votos_lista") or 0),
                "total_votos": str(p.get("total_votos") or 0),
            })
        for key, label in [
            ("votos_en_blanco", "VOTOS EN BLANCO"),
            ("votos_nulos", "VOTOS NULOS"),
            ("votos_no_marcados", "VOTOS NO MARCADOS"),
        ]:
            val = norm.get(key)
            if val is not None:
                sections.append({"tipo": key, "nombre": label, "total_votos": str(val)})

        result_data = {
            "download_id": download_id,
            "municipio_cod": municipio_cod,
            "zona_cod": zona_cod,
            "puesto_cod": puesto_cod,
            "mesa": mesa,
            "corporacion": corporacion,
            "votantes_e11": votantes_e11,
            "votos_urna": votos_urna,
            "ph_votos_lista": ph_lista,
            "ph_total_votos": ph_total,
            "all_sections_json": json.dumps(sections, ensure_ascii=False),
            "ocr_confidence": confidence,
            "total_paginas": meta.get("pages_sent"),
            "processing_time_s": processing_time,
            "nivel_alerta": nivel_alerta,
            "validacion_json": json.dumps(validacion, ensure_ascii=False),
            "status": "processed",
            "processed_at": datetime.now().isoformat(),
        }

        result_id = await db.insert_result(result_data)

        await event_bus.publish("ocr_complete", {
            "municipio_cod": municipio_cod,
            "zona_cod": zona_cod,
            "puesto_cod": puesto_cod,
            "mesa": mesa,
            "corporacion": corporacion,
            "ph_total_votos": ph_total,
            "confidence": confidence,
        })

        return result_id

    except Exception as e:
        processing_time = (datetime.now() - start_time).total_seconds()
        error_data = {
            "download_id": download_id,
            "municipio_cod": municipio_cod,
            "zona_cod": zona_cod,
            "puesto_cod": puesto_cod,
            "mesa": mesa,
            "corporacion": corporacion,
            "status": "error",
            "error_message": str(e),
            "processing_time_s": processing_time,
            "processed_at": datetime.now().isoformat(),
        }
        await db.insert_result(error_data)

        await event_bus.publish("ocr_error", {
            "municipio_cod": municipio_cod,
            "mesa": mesa,
            "corporacion": corporacion,
            "error": str(e),
        })
        raise
