"""E-14 Presidential template management — region definitions for the form layout."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from backend.config import BASE_DIR, DATA_DIR

router = APIRouter(prefix="/api/template", tags=["template"])

# ── Paths ─────────────────────────────────────────────────────────────────────
_TEMPLATE_JSON = DATA_DIR / "e14_template.json"
_TEST_PDF_DIR = BASE_DIR / "E14 TEST Presidencial"

# Pick the first test PDF alphabetically
def _find_test_pdf() -> Path | None:
    if not _TEST_PDF_DIR.exists():
        return None
    pdfs = sorted(_TEST_PDF_DIR.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def _load_regions() -> dict:
    if _TEMPLATE_JSON.exists():
        try:
            return json.loads(_TEMPLATE_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "updated_at": None, "regions": []}


def _save_regions(data: dict):
    data["updated_at"] = datetime.now().isoformat()
    _TEMPLATE_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Render helpers ─────────────────────────────────────────────────────────────

def _render_page_png(pdf_path: Path, page_num: int, scale: float = 1.5) -> bytes:
    """Render page (1-indexed) of PDF to PNG at given scale."""
    doc = fitz.open(str(pdf_path))
    idx = min(max(0, page_num - 1), len(doc) - 1)
    page = doc[idx]
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def _render_crop_png(pdf_path: Path, page_num: int,
                     x0_pct: float, y0_pct: float,
                     x1_pct: float, y1_pct: float,
                     scale: float = 2.0) -> bytes:
    """Render a percentage crop of a page as PNG."""
    doc = fitz.open(str(pdf_path))
    idx = min(max(0, page_num - 1), len(doc) - 1)
    page = doc[idx]
    r = page.rect
    crop = fitz.Rect(
        r.x0 + r.width  * x0_pct,
        r.y0 + r.height * y0_pct,
        r.x0 + r.width  * x1_pct,
        r.y0 + r.height * y1_pct,
    )
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, clip=crop)
    return pix.tobytes("png")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/info")
def get_template_info():
    """Return metadata about the test PDF and saved regions."""
    pdf = _find_test_pdf()
    regions_data = _load_regions()
    return {
        "test_pdf": str(pdf.name) if pdf else None,
        "test_pdf_pages": len(fitz.open(str(pdf))) if pdf else 0,
        "regions_count": len(regions_data.get("regions", [])),
        "updated_at": regions_data.get("updated_at"),
    }


@router.get("/test-page/{page_num}")
def get_test_page(page_num: int, scale: float = Query(default=1.5, ge=0.3, le=3.0)):
    """Return PNG of the test E-14 page (1-indexed)."""
    pdf = _find_test_pdf()
    if not pdf:
        raise HTTPException(status_code=404, detail="No test PDF found in 'E14 TEST Presidencial/'")
    import asyncio, concurrent.futures
    png = _render_page_png(pdf, page_num, scale=scale)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@router.get("/test-crop")
def get_test_crop(
    page: int = Query(default=1, ge=1),
    x0: float = Query(default=0.0),
    y0: float = Query(default=0.0),
    x1: float = Query(default=1.0),
    y1: float = Query(default=1.0),
    scale: float = Query(default=2.0, ge=0.5, le=4.0),
):
    """Return PNG crop of test page given percentage coordinates."""
    pdf = _find_test_pdf()
    if not pdf:
        raise HTTPException(status_code=404, detail="No test PDF found")
    png = _render_crop_png(pdf, page, x0, y0, x1, y1, scale=scale)
    return Response(content=png, media_type="image/png")


@router.get("/regions")
def get_regions():
    """Return all saved template region definitions."""
    return _load_regions()


class RegionItem(BaseModel):
    id: str
    tipo: str
    label: str
    page: int
    x0_pct: float
    y0_pct: float
    x1_pct: float
    y1_pct: float
    numero: int | None = None
    nombre: str | None = None
    partido: str | None = None


class SaveRegionsRequest(BaseModel):
    regions: list[RegionItem]


@router.put("/regions")
def save_regions(body: SaveRegionsRequest):
    """Save all template region definitions (full replace)."""
    data = {"version": 1, "regions": [r.model_dump() for r in body.regions]}
    _save_regions(data)
    return {"saved": len(body.regions), "updated_at": data["updated_at"]}


# ── Bootstrap default regions ─────────────────────────────────────────────────

@router.post("/bootstrap-defaults")
def bootstrap_defaults():
    """Pre-rellena la plantilla con las regiones default del E-14 presidencial 2026.
    Solo añade regiones que no existen ya (no sobreescribe las definidas por el usuario).
    """
    from backend.services.local_ocr import get_default_regions
    current = _load_regions()
    existing = {r.get("id") for r in current.get("regions", [])}

    defaults = get_default_regions()
    added = [r for r in defaults if r["id"] not in existing]
    merged = current.get("regions", []) + added

    data = {"version": 1, "regions": merged}
    _save_regions(data)
    return {"total": len(merged), "added": len(added), "updated_at": data["updated_at"]}


# ── Run OCR local on test PDF ──────────────────────────────────────────────────

@router.post("/run-ocr-local")
async def run_ocr_local(pdf_index: int = 0):
    """Ejecuta OCR local sobre uno de los PDFs de test presidencial.
    pdf_index: 0-2 (0=primer PDF, 1=segundo, 2=tercero).
    """
    import asyncio
    from backend.services.local_ocr import process_e14_local

    pdfs = sorted(_TEST_PDF_DIR.glob("*.pdf")) if _TEST_PDF_DIR.exists() else []
    if not pdfs:
        raise HTTPException(status_code=404, detail="No hay PDFs de test en 'E14 TEST Presidencial/'")
    if pdf_index >= len(pdfs):
        pdf_index = 0

    pdf_path = pdfs[pdf_index]
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: process_e14_local(str(pdf_path)))

    # Condensar para la respuesta — no incluir datos internos pesados
    formulas_out = [
        {
            "numero": f.get("codigo"),
            "nombre": f.get("nombre"),
            "partido": f.get("partido"),
            "votos": f.get("total_votos", 0),
            "confianza": f.get("confianza", 0),
        }
        for f in result.get("partidos", [])
    ]

    firmas = result.get("firmas", [])
    return {
        "pdf": pdf_path.name,
        "nivelacion": result.get("nivelacion", {}),
        "formulas": formulas_out,
        "votos_en_blanco": result.get("votos_en_blanco", 0),
        "votos_nulos": result.get("votos_nulos", 0),
        "votos_no_marcados": result.get("votos_no_marcados", 0),
        "total_formula_votes": result.get("total_formula_votes", 0),
        "firmas": firmas,
        "firmas_count": result.get("firmas_count", 0),
        "firmas_ok": result.get("firmas_count", 0) == 6,
        "tiene_recuento": result.get("tiene_recuento"),
        "errores_aritmeticos": result.get("errores_aritmeticos", []),
        "confianza_general": result.get("confianza_general", 0),
        "meta": result.get("_meta", {}),
    }


# ── Signature screenshot for a real mesa PDF ──────────────────────────────────

@router.get("/signatures/{mun}/{zona}/{puesto}/{mesa}")
async def get_signatures_screenshot(mun: str, zona: str, puesto: str, mesa: int):
    """Return PNG of page 3 (signatures) from a real mesa E-14 PDF."""
    from backend import database as db

    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT filepath FROM e14_downloads
           WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ? AND mesa = ?
             AND corporacion = 'PRES'
           LIMIT 1""",
        (mun, zona, puesto, mesa),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="PDF no encontrado")

    filepath = rows[0]["filepath"]
    pdf_path = Path(filepath)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Archivo PDF no encontrado en disco")

    import asyncio
    loop = asyncio.get_event_loop()
    png = await loop.run_in_executor(None, lambda: _render_page_png(pdf_path, 3, scale=1.5))
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})
