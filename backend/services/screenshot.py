"""Renders a crop of the Pacto vote area from an E-14 PDF page."""
import fitz  # PyMuPDF

from backend.config import CLAUDE_SEN_PACTO_PAGE, CLAUDE_CAM_PACTO_PAGE


def render_pacto_crop(filepath: str, corporacion: str) -> bytes:
    """Return PNG bytes of the Pacto vote table area from the relevant PDF page."""
    doc = fitz.open(filepath)

    corp = corporacion.upper()
    if corp in ("SEN", "SENADO"):
        page_idx = max(0, CLAUDE_SEN_PACTO_PAGE - 1)
    elif CLAUDE_CAM_PACTO_PAGE > 0:
        page_idx = max(0, CLAUDE_CAM_PACTO_PAGE - 1)
    else:
        page_idx = 0

    page_idx = min(page_idx, len(doc) - 1)
    page = doc[page_idx]

    # Crop tightly around the Pacto Histórico vote row.
    # Coordinates calibrated from real Antioquia E-14 forms per corporation.
    r = page.rect
    if corp in ("SEN", "SENADO"):
        # SEN: Pacto appears at ~21%-36% of page height (page 5)
        crop = fitz.Rect(
            r.x0 + r.width  * 0.004,
            r.y0 + r.height * 0.214,
            r.x0 + r.width  * 1.007,
            r.y0 + r.height * 0.362,
        )
    else:
        # CAM: Pacto appears at ~32%-45% of page height (page 1)
        crop = fitz.Rect(
            r.x0 + r.width  * 0.004,
            r.y0 + r.height * 0.322,
            r.x0 + r.width  * 0.993,
            r.y0 + r.height * 0.445,
        )

    # Render at 2× zoom for legibility
    mat = fitz.Matrix(2.0, 2.0)
    pix = page.get_pixmap(matrix=mat, clip=crop)
    return pix.tobytes("png")
