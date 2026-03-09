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
            r = hits[0]
            return i, r
    return None


def _pacto_page_idx(doc: fitz.Document, corp: str) -> int:
    """Return the page index where the Pacto section is (or should be)."""
    found = _find_pacto_rect(doc)
    if found:
        return found[0]
    if corp.upper() in ("SEN", "SENADO"):
        return min(max(0, CLAUDE_SEN_PACTO_PAGE - 1), len(doc) - 1)
    return min(max(0, (CLAUDE_CAM_PACTO_PAGE or 1) - 1), len(doc) - 1)


def render_full_page(filepath: str, corporacion: str) -> bytes:
    """Return PNG of the full page where the Pacto section appears (for crop editor)."""
    doc = fitz.open(filepath)
    page_idx = _pacto_page_idx(doc, corporacion)
    page = doc[page_idx]
    mat = fitz.Matrix(1.5, 1.5)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def render_pacto_crop(filepath: str, corporacion: str,
                      override: tuple[float, float, float, float] | None = None) -> bytes:
    """Return PNG bytes of the Pacto vote table area from the relevant PDF page.

    override: (x0_pct, y0_pct, x1_pct, y1_pct) as 0–1 fractions of page size.
              When provided, skips auto-detection and uses these coordinates.
    """
    doc = fitz.open(filepath)
    corp = corporacion.upper()

    # ── Manual crop override ───────────────────────────────────────────────────
    if override:
        x0p, y0p, x1p, y1p = override
        page_idx = _pacto_page_idx(doc, corp)
        page = doc[page_idx]
        r = page.rect
        crop = fitz.Rect(
            r.x0 + r.width  * x0p,
            r.y0 + r.height * y0p,
            r.x0 + r.width  * x1p,
            r.y0 + r.height * y1p,
        )
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat, clip=crop)
        return pix.tobytes("png")

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
        page_idx = max(0, CLAUDE_SEN_PACTO_PAGE - 1)
        y_top, y_bot = 0.214, 0.362
    else:
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
