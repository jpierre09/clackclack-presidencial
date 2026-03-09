"""Renders a crop of the Pacto vote area from an E-14 PDF page.

Strategy:
  1. Search all pages for "PACTO" text to find the exact location.
  2. If found, crop a fixed-height band around it (±padding).
  3. If not found, fall back to calibrated page+percentage coordinates.
"""
import fitz  # PyMuPDF

from backend.config import CLAUDE_SEN_PACTO_PAGE, CLAUDE_CAM_PACTO_PAGE

# Padding above/below the found PACTO text rect (in PDF points)
_PADDING_TOP = 10
_PADDING_BOTTOM = 60   # enough to include the "VOTOS POR LA AGRUPACIÓN" row


def _find_pacto_rect(doc: fitz.Document) -> tuple[int, fitz.Rect] | None:
    """Search all pages for 'PACTO' text. Returns (page_idx, rect) or None."""
    for i, page in enumerate(doc):
        hits = page.search_for("PACTO")
        if hits:
            # Use the first hit (topmost match on the page)
            r = hits[0]
            return i, r
    return None


def render_pacto_crop(filepath: str, corporacion: str) -> bytes:
    """Return PNG bytes of the Pacto vote table area from the relevant PDF page."""
    doc = fitz.open(filepath)
    corp = corporacion.upper()

    # ── Try text search first ──────────────────────────────────────────────────
    found = _find_pacto_rect(doc)
    if found:
        page_idx, hit = found
        page = doc[page_idx]
        r = page.rect
        crop = fitz.Rect(
            r.x0,
            max(r.y0, hit.y0 - _PADDING_TOP),
            r.x1,
            min(r.y1, hit.y1 + _PADDING_BOTTOM),
        )
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat, clip=crop)
        return pix.tobytes("png")

    # ── Fallback: calibrated page + percentage crop ────────────────────────────
    if corp in ("SEN", "SENADO"):
        # SEN: Pacto appears at ~21%-36% of page height (page 5)
        page_idx = max(0, CLAUDE_SEN_PACTO_PAGE - 1)
        y_top, y_bot = 0.214, 0.362
    else:
        # CAM: Pacto appears at ~32%-45% of page height (page 1)
        page_idx = max(0, (CLAUDE_CAM_PACTO_PAGE or 1) - 1)
        y_top, y_bot = 0.322, 0.445

    page_idx = min(page_idx, len(doc) - 1)
    page = doc[page_idx]
    r = page.rect
    crop = fitz.Rect(
        r.x0 + r.width  * 0.004,
        r.y0 + r.height * y_top,
        r.x0 + r.width  * 0.993,
        r.y0 + r.height * y_bot,
    )
    mat = fitz.Matrix(2.0, 2.0)
    pix = page.get_pixmap(matrix=mat, clip=crop)
    return pix.tobytes("png")
