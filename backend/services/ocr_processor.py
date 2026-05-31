"""OCR processor — usa EXCLUSIVAMENTE OCR local (EasyOCR) sin dependencia de Claude API."""
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

from backend import database as db
from backend.services.event_bus import event_bus

log = logging.getLogger("ocr_processor")

_NOT_DIGITIZED_KW = [
    "no digitalizada", "no digitalizado", "no disponible",
    "formulario no disponible", "acta no disponible",
    "pagina no disponible", "página no disponible",
    "not available", "documento no disponible",
]


def _page_is_not_digitized(pdf_path: str, page_index: int) -> bool:
    """Return True if the target page is a 'not digitized' placeholder."""
    try:
        doc = fitz.open(pdf_path)
        num_pages = len(doc)
        candidates = [page_index]
        if page_index >= num_pages:
            candidates = [0]
        elif page_index > 0:
            candidates.append(0)

        if page_index > 0 and num_pages > 1:
            mat0 = fitz.Matrix(0.25, 0.25)
            pix0 = doc[0].get_pixmap(matrix=mat0, colorspace=fitz.csGRAY)
            s0 = bytes(pix0.samples)
            if s0 and sum(1 for b in s0 if b > 210) / len(s0) < 0.78:
                doc.close()
                return False

        for pi in candidates:
            if pi >= num_pages:
                continue
            page = doc[pi]
            if any(kw in page.get_text().lower() for kw in _NOT_DIGITIZED_KW):
                doc.close()
                return True
            mat = fitz.Matrix(0.25, 0.25)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            h, w = pix.height, pix.width
            samples = bytes(pix.samples)
            if len(samples) < 200 or h < 10:
                continue
            white_ratio = sum(1 for b in samples if b > 210) / len(samples)
            bottom = samples[int(h * 0.60) * w:]
            bottom_white = sum(1 for b in bottom if b > 210) / len(bottom) if bottom else 0.0
            if white_ratio > 0.82 and bottom_white > 0.97:
                doc.close()
                return True

        doc.close()
        return False
    except Exception:
        return False


async def process_e14(download_id: int, filepath: str,
                      municipio_cod: str, zona_cod: str, puesto_cod: str,
                      mesa: int, corporacion: str, skip_nd_check: bool = False):
    """Procesa un PDF de E-14 presidencial con OCR local y guarda los resultados."""
    start_time = datetime.now()

    try:
        loop = asyncio.get_running_loop()

        # ── Pre-check: acta no digitalizada ────────────────────────────────
        if not skip_nd_check:
            not_digitized = await loop.run_in_executor(
                None, lambda: _page_is_not_digitized(filepath, 0)
            )
            if not_digitized:
                await db.insert_result({
                    "download_id": download_id,
                    "municipio_cod": municipio_cod,
                    "zona_cod": zona_cod,
                    "puesto_cod": puesto_cod,
                    "mesa": mesa,
                    "corporacion": corporacion,
                    "status": "not_digitized",
                    "error_message": "Pagina no digitalizada",
                    "processing_time_s": 0.0,
                    "processed_at": datetime.now().isoformat(),
                })
                return None

        # ── OCR local (EasyOCR) ─────────────────────────────────────────────
        from backend.services.local_ocr import process_e14_local
        norm = await loop.run_in_executor(None, lambda: process_e14_local(filepath))

        formulas   = norm.get("partidos", [])
        niv        = norm.get("nivelacion", {})
        votantes_e11 = niv.get("total_sufragantes_e11")
        votos_urna   = niv.get("total_votos_urna")
        total_formula_votes = norm.get("total_formula_votes", 0)
        validacion  = norm.get("_validacion", {})
        confidence  = norm.get("confianza_general", 75)
        meta        = norm.get("_meta", {})
        encabezado  = norm.get("encabezado_ocr")  # nuevo: datos del encabezado leídos del PDF
        processing_time = meta.get("total_time_s",
                                   (datetime.now() - start_time).total_seconds())

        # Serializar secciones para all_sections_json
        sections = []
        for f in formulas:
            sections.append({
                "tipo": "formula",
                "nombre":   f.get("nombre", ""),
                "partido":  f.get("partido", ""),
                "candidato_presidente":    f.get("candidato_presidente", ""),
                "candidato_vicepresidente": f.get("candidato_vicepresidente", ""),
                "codigo": f.get("codigo", ""),
                "votos_lista": str(f.get("votos_lista") or 0),
                "total_votos": str(f.get("total_votos") or 0),
            })
        for key, label in [
            ("votos_en_blanco", "VOTOS EN BLANCO"),
            ("votos_nulos",     "VOTOS NULOS"),
            ("votos_no_marcados", "VOTOS NO MARCADOS"),
        ]:
            val = norm.get(key)
            if val is not None:
                sections.append({"tipo": key, "nombre": label, "total_votos": str(val)})

        firmas        = norm.get("firmas", [])
        tiene_recuento = norm.get("tiene_recuento")

        result_data = {
            "download_id":    download_id,
            "municipio_cod":  municipio_cod,
            "zona_cod":       zona_cod,
            "puesto_cod":     puesto_cod,
            "mesa":           mesa,
            "corporacion":    corporacion,
            "votantes_e11":   votantes_e11,
            "votos_urna":     votos_urna,
            "ph_votos_lista": total_formula_votes,
            "ph_total_votos": total_formula_votes,
            "all_sections_json": json.dumps(sections, ensure_ascii=False),
            "ocr_confidence": confidence,
            "total_paginas":  meta.get("pages_processed"),
            "processing_time_s": processing_time,
            "nivel_alerta":   validacion.get("nivel_alerta", "OK"),
            "validacion_json": json.dumps(validacion, ensure_ascii=False),
            "firmas_json":    json.dumps(firmas) if firmas else None,
            "tiene_recuento": 1 if tiene_recuento else (0 if tiene_recuento is False else None),
            "encabezado_json": json.dumps(encabezado, ensure_ascii=False) if encabezado else None,
            "status":         "processed",
            "processed_at":   datetime.now().isoformat(),
        }

        result_id = await db.insert_result(result_data)
        log.info("OCR local OK mesa=%s conf=%s%%", mesa, confidence)

        await event_bus.publish("ocr_complete", {
            "municipio_cod": municipio_cod,
            "zona_cod":      zona_cod,
            "puesto_cod":    puesto_cod,
            "mesa":          mesa,
            "corporacion":   corporacion,
            "total_formula_votes": total_formula_votes,
            "confidence":    confidence,
        })
        return result_id

    except Exception as exc:
        processing_time = (datetime.now() - start_time).total_seconds()
        await db.insert_result({
            "download_id":   download_id,
            "municipio_cod": municipio_cod,
            "zona_cod":      zona_cod,
            "puesto_cod":    puesto_cod,
            "mesa":          mesa,
            "corporacion":   corporacion,
            "status":        "error",
            "error_message": str(exc),
            "processing_time_s": processing_time,
            "processed_at":  datetime.now().isoformat(),
        })
        await event_bus.publish("ocr_error", {
            "municipio_cod": municipio_cod,
            "mesa": mesa, "corporacion": corporacion,
            "error": str(exc),
        })
        raise
