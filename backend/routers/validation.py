"""Validation and correction endpoints."""
from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path
from backend import database as db
from backend.models import CorrectionRequest
from backend.services import alert_engine

router = APIRouter(prefix="/api/validation", tags=["validation"])


@router.get("/mesa/{mun}/{zona}/{puesto}/{mesa}/{corp}")
async def get_validation_data(mun: str, zona: str, puesto: str, mesa: int, corp: str):
    """Get OCR result + PDF path for side-by-side validation."""
    detail = await db.get_mesa_detail(mun, zona, puesto, mesa)
    result = None
    for r in detail["results"]:
        if r["corporacion"] == corp.upper():
            result = r
            break
    return {
        "result": result,
        "puesto": detail["puesto"],
        "alerts": detail["alerts"],
    }


@router.put("/mesa/{mun}/{zona}/{puesto}/{mesa}/{corp}")
async def correct_result(mun: str, zona: str, puesto: str, mesa: int,
                          corp: str, correction: CorrectionRequest):
    """Apply manual correction to OCR results."""
    await db.update_result_correction(
        mun, zona, puesto, mesa, corp.upper(),
        correction.model_dump(exclude_none=True)
    )
    # Re-evaluate alerts
    await alert_engine.evaluate_mesa(mun, zona, puesto, mesa)
    return {"status": "corrected"}


@router.get("/pdf/{filepath:path}")
async def serve_pdf(filepath: str):
    """Serve E-14 PDF file."""
    from backend.config import BASE_DIR
    full_path = (BASE_DIR / filepath).resolve()
    try:
        full_path.relative_to(BASE_DIR.resolve())
    except ValueError:
        return {"error": "Invalid path"}
    if not full_path.exists():
        return {"error": "File not found"}
    return FileResponse(str(full_path), media_type="application/pdf")
