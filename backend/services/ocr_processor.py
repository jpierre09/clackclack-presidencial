"""OCR processor - wraps Claude Vision API for async E-14 processing."""
import json
import asyncio
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

from backend.config import (
    CLAUDE_MAX_PAGES_SEN, CLAUDE_MAX_PAGES_CAM,
    CLAUDE_SEN_PACTO_PAGE, CLAUDE_CAM_PACTO_PAGE,
    PH_PATTERNS,
)
from backend import database as db
from backend.services.event_bus import event_bus
from backend.services.claude_ocr import process_e14_pdf, normalize_result, validate_result

# Keywords that indicate a page that has not been digitized yet by Registraduría
_NOT_DIGITIZED_KW = [
    "no digitalizada",
    "no digitalizado",
    "no disponible",
    "formulario no disponible",
    "acta no disponible",
    "pagina no disponible",
    "página no disponible",
    "not available",
    "documento no disponible",
]


def _page_is_not_digitized(pdf_path: str, page_index: int) -> bool:
    """Return True if the target page is a 'not digitized' placeholder.

    Two detection methods:
    1. Text extraction — works for digital PDFs with embedded text.
    2. Visual analysis — works for image PDFs: a real E14 has a dense table
       with many dark lines/text pixels; a placeholder page is nearly blank.

    If the requested page_index is beyond the PDF length (e.g. we want page 4
    for SEN but the PDF only has 1 page), we fall back to checking page 0 —
    this catches single-page "PÁGINA NO DIGITALIZADA" PDFs.
    """
    try:
        doc = fitz.open(pdf_path)
        num_pages = len(doc)

        # Build list of pages to inspect: target page, then page 0 as fallback
        candidates = [page_index]
        if page_index >= num_pages:
            candidates = [0]  # PDF shorter than expected → check first page
        elif page_index > 0:
            candidates.append(0)  # Also check first page for early placeholders

        # Early-exit guard: if checking a non-first page AND the PDF has multiple
        # pages, verify that page 0 isn't a dense real E14 table.  A real E14
        # front page is full of party rows and grid lines (white_ratio < 0.78).
        # Placeholder PDFs are always sparse on page 0 as well (≥ 0.82 white).
        # This prevents false positives on real E14s where the target page
        # (e.g. SEN page 5) has very few rows and looks mostly blank.
        if page_index > 0 and num_pages > 1:
            mat0 = fitz.Matrix(0.25, 0.25)
            pix0 = doc[0].get_pixmap(matrix=mat0, colorspace=fitz.csGRAY)
            s0 = bytes(pix0.samples)
            if s0:
                white0 = sum(1 for b in s0 if b > 210) / len(s0)
                if white0 < 0.78:
                    doc.close()
                    return False  # Dense first page → genuine E14

        for pi in candidates:
            if pi >= num_pages:
                continue
            page = doc[pi]

            # Method 1: extractable text
            text = page.get_text().lower()
            if any(kw in text for kw in _NOT_DIGITIZED_KW):
                doc.close()
                return True

            # Method 2: visual analysis for image-based PDFs.
            # The "PÁGINA NO DIGITALIZADA" placeholder has:
            #   - Registraduría logo in the top ~30 % of the page
            #   - Bold text "PÁGINA NO DIGITALIZADA" in the center
            #   - Bottom ~40 % completely empty/white
            # Real E14 forms have dense table grids covering the full page.
            mat = fitz.Matrix(0.25, 0.25)  # ¼ scale — fast, enough for ratio
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            h, w = pix.height, pix.width
            samples = bytes(pix.samples)

            if len(samples) < 200 or h < 10:
                continue

            # Overall near-white ratio (pixel value > 210 in 0–255 grayscale)
            white_px = sum(1 for b in samples if b > 210)
            white_ratio = white_px / len(samples)

            # Bottom 40 % of page — placeholder is 100 % blank there;
            # real E14s always have table rows with data in the lower portion.
            bottom_start = int(h * 0.60) * w
            bottom_samples = samples[bottom_start:]
            bottom_white_ratio = (
                sum(1 for b in bottom_samples if b > 210) / len(bottom_samples)
                if bottom_samples else 0.0
            )

            # Match: >82 % white overall AND >97 % white in bottom 40 %
            if white_ratio > 0.82 and bottom_white_ratio > 0.97:
                doc.close()
                return True

        doc.close()
        return False

    except Exception:
        return False


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
        loop = asyncio.get_running_loop()
        start_page, max_pages = _pages_for(corporacion)

        # ── Pre-check: skip PDFs that Registraduría hasn't digitized yet ──────
        not_digitized = await loop.run_in_executor(
            None, lambda: _page_is_not_digitized(filepath, start_page)
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
                "error_message": "Página no digitalizada por la Registraduría",
                "processing_time_s": 0.0,
                "processed_at": datetime.now().isoformat(),
            })
            return None

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
