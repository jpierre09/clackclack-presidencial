"""Renders a crop of the vote area from a presidential E-14 PDF page.

Strategy:
  1. Use manual crop override if provided.
  2. Fall back to calibrated page+percentage coordinates for page 1.
"""
import fitz  # PyMuPDF

from backend.config import CLAUDE_PRES_PAGE

_DEFAULT_Y_TOP = 0.15
_DEFAULT_Y_BOT = 0.90


def _pres_page_idx(doc: fitz.Document) -> int:
    """Return the page index for the presidential E-14 vote section."""
    return min(max(0, CLAUDE_PRES_PAGE - 1), len(doc) - 1)


def render_full_page(filepath: str, corporacion: str) -> bytes:
    """Return PNG of the full page for the given E-14 (corp argument ignored, always PRES)."""
    doc = fitz.open(filepath)
    page_idx = _pres_page_idx(doc)
    page = doc[page_idx]
    mat = fitz.Matrix(1.5, 1.5)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def render_pacto_crop(filepath: str, corporacion: str,
                      override: tuple[float, float, float, float] | None = None) -> bytes:
    """Return PNG bytes of the vote area from the presidential E-14 PDF page.

    override: (x0_pct, y0_pct, x1_pct, y1_pct) as 0-1 fractions of page size.
              When provided, uses these exact coordinates.
    """
    doc = fitz.open(filepath)
    page_idx = _pres_page_idx(doc)
    page = doc[page_idx]
    r = page.rect

    if override:
        x0p, y0p, x1p, y1p = override
        crop = fitz.Rect(
            r.x0 + r.width  * x0p,
            r.y0 + r.height * y0p,
            r.x0 + r.width  * x1p,
            r.y0 + r.height * y1p,
        )
    else:
        crop = fitz.Rect(
            r.x0 + r.width  * 0.004,
            r.y0 + r.height * _DEFAULT_Y_TOP,
            r.x0 + r.width  * 0.993,
            r.y0 + r.height * _DEFAULT_Y_BOT,
        )

    mat = fitz.Matrix(2.0, 2.0)
    pix = page.get_pixmap(matrix=mat, clip=crop)
    return pix.tobytes("png")
