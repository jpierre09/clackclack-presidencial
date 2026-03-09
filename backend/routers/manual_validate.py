"""Tinder-style manual validation tool API."""
from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

import io
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend import database as db
from backend.config import BASE_DIR, E14_DOWNLOADS_DIR, VALIDATE_SETUP_TOKEN
from backend.services import alert_engine
from backend.services.event_bus import event_bus

router = APIRouter(prefix="/api/validar", tags=["manual-validate"])

_ITERATIONS = 260_000


def _safe_within(path, root) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"pbkdf2:{salt}:{dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, dk_hex = stored.split(":", 2)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return secrets.compare_digest(dk.hex(), dk_hex)


async def _require_auth(x_session_token: Annotated[str | None, Header()] = None) -> str:
    if not x_session_token:
        raise HTTPException(status_code=401, detail="No session token")
    username = await db.get_session(x_session_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return username


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    setup_token: str


class SubmitRequest(BaseModel):
    municipio_cod: str
    zona_cod: str
    puesto_cod: str
    mesa: int
    corporacion: str
    action: str               # "approved" | "corrected"
    corrected_ph_votes: int | None = None


class AdminCropRequest(BaseModel):
    municipio_cod: str
    zona_cod: str
    puesto_cod: str
    mesa: int
    corporacion: str
    x0: float
    y0: float
    x1: float
    y1: float
    corrected_ph_votes: int | None = None
    admin_token: str


class NoveltyRequest(BaseModel):
    municipio_cod: str
    zona_cod: str
    puesto_cod: str
    mesa: int
    corporacion: str
    note: str


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.post("/auth/login")
async def login(req: LoginRequest):
    user = await db.get_user(req.username)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    if not _verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = secrets.token_urlsafe(32)
    await db.create_session(token, req.username)
    return {"token": token, "username": req.username}


@router.post("/auth/logout")
async def logout(x_session_token: Annotated[str | None, Header()] = None):
    if x_session_token:
        username = await db.get_session(x_session_token)
        if username:
            await db.release_claim(username)
        await db.delete_session(x_session_token)
    return {"status": "ok"}


@router.get("/auth/me")
async def me(username: str = Depends(_require_auth)):
    return {"username": username}


# ── Admin ─────────────────────────────────────────────────────────────────────

@router.post("/admin/crop-override")
async def admin_crop_override(req: AdminCropRequest):
    """Set a manual crop override for a PDF (admin only)."""
    if not VALIDATE_SETUP_TOKEN:
        raise HTTPException(status_code=503, detail="VALIDATE_SETUP_TOKEN not configured")
    if not secrets.compare_digest(req.admin_token, VALIDATE_SETUP_TOKEN):
        raise HTTPException(status_code=403, detail="Token inválido")

    corp = req.corporacion.upper()
    await db.save_crop_override(
        req.municipio_cod, req.zona_cod, req.puesto_cod,
        req.mesa, corp, "admin",
        req.x0, req.y0, req.x1, req.y1,
    )

    if req.corrected_ph_votes is not None:
        await db.submit_validation({
            "municipio_cod": req.municipio_cod,
            "zona_cod": req.zona_cod,
            "puesto_cod": req.puesto_cod,
            "mesa": req.mesa,
            "corporacion": corp,
            "validated_by": "admin",
            "action": "corrected",
            "corrected_ph_votes": req.corrected_ph_votes,
        })
        await alert_engine.evaluate_mesa(
            req.municipio_cod, req.zona_cod, req.puesto_cod, req.mesa
        )

    return {"status": "ok"}


@router.post("/admin/create-user")
async def create_user(req: CreateUserRequest):
    if not VALIDATE_SETUP_TOKEN:
        raise HTTPException(status_code=503, detail="VALIDATE_SETUP_TOKEN not configured")
    if not secrets.compare_digest(req.setup_token, VALIDATE_SETUP_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid setup token")
    if len(req.username) < 2 or len(req.password) < 6:
        raise HTTPException(status_code=400, detail="username >= 2 chars, password >= 6 chars")
    ok = await db.create_user(req.username, _hash_password(req.password))
    if not ok:
        raise HTTPException(status_code=409, detail="Username already exists")
    return {"status": "created", "username": req.username}


# ── Queue ─────────────────────────────────────────────────────────────────────

@router.get("/queue/next")
async def get_next(username: str = Depends(_require_auth)):
    item = await db.get_next_unvalidated(username)
    stats = await db.get_validation_stats()
    return {"item": item, "stats": stats}


@router.get("/queue/stats")
async def get_stats(username: str = Depends(_require_auth)):
    return await db.get_validation_stats()


# ── Screenshot ────────────────────────────────────────────────────────────────

async def _resolve_pdf_path(mun: str, zona: str, puesto: str, mesa: int, corp: str):
    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT d.filepath FROM e14_results r
           JOIN e14_downloads d ON d.id = r.download_id
           WHERE r.municipio_cod=? AND r.zona_cod=? AND r.puesto_cod=?
             AND r.mesa=? AND r.corporacion=? LIMIT 1""",
        (mun, zona, puesto, mesa, corp.upper()),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Result not found")
    raw = rows[0]["filepath"]
    # Support both absolute paths (Railway /persist/...) and legacy relative paths
    from pathlib import Path as _Path
    import os as _os
    if _os.path.isabs(raw):
        full_path = _Path(raw).resolve()
    else:
        full_path = (BASE_DIR / raw).resolve()
    # Security: must be inside E14_DOWNLOADS_DIR or BASE_DIR
    allowed = [E14_DOWNLOADS_DIR.resolve(), BASE_DIR.resolve()]
    if not any(_safe_within(full_path, root) for root in allowed):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")
    return full_path


@router.get("/screenshot/{mun}/{zona}/{puesto}/{mesa}/{corp}")
async def get_screenshot(mun: str, zona: str, puesto: str, mesa: int, corp: str):
    from backend.services.screenshot import render_pacto_crop
    full_path = await _resolve_pdf_path(mun, zona, puesto, mesa, corp)
    override = await db.get_crop_override(mun, zona, puesto, mesa, corp.upper())
    return Response(
        content=render_pacto_crop(str(full_path), corp, override=override),
        media_type="image/png",
    )


@router.get("/fullpage/{mun}/{zona}/{puesto}/{mesa}/{corp}")
async def get_fullpage(mun: str, zona: str, puesto: str, mesa: int, corp: str):
    """Return the full PDF page image for the crop editor."""
    from backend.services.screenshot import render_full_page
    full_path = await _resolve_pdf_path(mun, zona, puesto, mesa, corp)
    return Response(content=render_full_page(str(full_path), corp), media_type="image/png")


# ── Submit single validation ──────────────────────────────────────────────────

@router.post("/submit")
async def submit(req: SubmitRequest, username: str = Depends(_require_auth)):
    if req.action not in ("approved", "corrected"):
        raise HTTPException(status_code=400, detail="action must be 'approved' or 'corrected'")
    if req.action == "corrected" and req.corrected_ph_votes is None:
        raise HTTPException(status_code=400, detail="corrected_ph_votes required")

    await db.submit_validation({
        "municipio_cod": req.municipio_cod,
        "zona_cod": req.zona_cod,
        "puesto_cod": req.puesto_cod,
        "mesa": req.mesa,
        "corporacion": req.corporacion.upper(),
        "validated_by": username,
        "action": req.action,
        "corrected_ph_votes": req.corrected_ph_votes,
    })

    # Evaluate discrepancy — fires only when both SEN and CAM are validated
    await alert_engine.evaluate_mesa(
        req.municipio_cod, req.zona_cod, req.puesto_cod, req.mesa
    )
    return {"status": "ok", "action": req.action}


# ── Novelty ───────────────────────────────────────────────────────────────────

@router.post("/novelty")
async def report_novelty(req: NoveltyRequest, username: str = Depends(_require_auth)):
    await db.add_novelty_note(
        req.municipio_cod, req.zona_cod, req.puesto_cod,
        req.mesa, req.corporacion.upper(), username, req.note,
    )
    await db.release_claim(username)
    await event_bus.publish("alert_created", {
        "municipio_cod": req.municipio_cod,
        "type": "novelty_report",
        "severity": "info",
    })
    return {"status": "ok"}


@router.get("/admin/validations")
async def list_validations(search: str = "", admin_token: str = ""):
    """List all validations for admin review (requires admin token)."""
    if not VALIDATE_SETUP_TOKEN or not secrets.compare_digest(admin_token, VALIDATE_SETUP_TOKEN):
        raise HTTPException(status_code=403, detail="Token inválido")
    return await db.get_all_validations(search)


class AdminCorrectRequest(BaseModel):
    validation_id: int
    corrected_ph_votes: int
    admin_token: str


@router.post("/admin/correct-validation")
async def admin_correct_validation(req: AdminCorrectRequest):
    """Admin override of a validator's submitted value."""
    if not VALIDATE_SETUP_TOKEN or not secrets.compare_digest(req.admin_token, VALIDATE_SETUP_TOKEN):
        raise HTTPException(status_code=403, detail="Token inválido")
    ok = await db.admin_correct_validation(req.validation_id, req.corrected_ph_votes, "admin")
    if not ok:
        raise HTTPException(status_code=404, detail="Validación no encontrada")
    # Look up the mesa to re-evaluate discrepancy
    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        "SELECT municipio_cod, zona_cod, puesto_cod, mesa FROM manual_validations WHERE id = ?",
        (req.validation_id,),
    )
    if rows:
        r = rows[0]
        await alert_engine.evaluate_mesa(r["municipio_cod"], r["zona_cod"], r["puesto_cod"], r["mesa"])
    return {"status": "ok", "validation_id": req.validation_id, "new_value": req.corrected_ph_votes}


@router.post("/undo")
async def undo_validation(username: str = Depends(_require_auth)):
    """Undo the validator's most recent submission and return that item."""
    item = await db.undo_last_validation(username)
    stats = await db.get_validation_stats()
    return {"item": item, "stats": stats}


@router.get("/admin/users")
async def list_users(admin_token: str = ""):
    if not VALIDATE_SETUP_TOKEN or not secrets.compare_digest(admin_token, VALIDATE_SETUP_TOKEN):
        raise HTTPException(status_code=403, detail="Token inválido")
    conn = await db.get_db()
    rows = await conn.execute_fetchall("SELECT id, username, is_active FROM users ORDER BY id")
    return [dict(r) for r in rows]


@router.delete("/admin/sessions")
async def clear_all_sessions(admin_token: str = ""):
    if not VALIDATE_SETUP_TOKEN or not secrets.compare_digest(admin_token, VALIDATE_SETUP_TOKEN):
        raise HTTPException(status_code=403, detail="Token inválido")
    conn = await db.get_db()
    await conn.execute("DELETE FROM sessions")
    await conn.execute("DELETE FROM queue_claims")
    await conn.commit()
    return {"status": "ok", "message": "Todas las sesiones y claims cerrados"}


@router.get("/novedades")
async def get_novedades():
    return await db.get_novelty_reports()


@router.get("/novedades/export")
async def export_novedades():
    """Download all novelty reports as Excel."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    rows = await db.get_novelty_reports()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Novedades"

    headers = [
        "ID", "Departamento", "Municipio", "Cód Municipio",
        "Zona", "Puesto", "Cód Puesto", "Mesa", "Corporación",
        "Validador", "Acción", "Fecha Validación",
        "Votos IA", "Votos Corregidos", "Votos Urna",
        "Nota de Novedad",
    ]

    # Header row styling
    header_fill = PatternFill("solid", fgColor="1D4ED8")
    header_font = Font(bold=True, color="FFFFFF")
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    # Data rows
    for row_idx, item in enumerate(rows, 2):
        ws.cell(row=row_idx, column=1, value=item.get("id"))
        ws.cell(row=row_idx, column=2, value=item.get("departamento") or "")
        ws.cell(row=row_idx, column=3, value=item.get("municipio") or item.get("municipio_cod"))
        ws.cell(row=row_idx, column=4, value=item.get("municipio_cod"))
        ws.cell(row=row_idx, column=5, value=item.get("zona_cod"))
        ws.cell(row=row_idx, column=6, value=item.get("puesto_nombre") or "")
        ws.cell(row=row_idx, column=7, value=item.get("puesto_cod"))
        ws.cell(row=row_idx, column=8, value=item.get("mesa"))
        ws.cell(row=row_idx, column=9, value=item.get("corporacion"))
        ws.cell(row=row_idx, column=10, value=item.get("validated_by"))
        ws.cell(row=row_idx, column=11, value=item.get("action"))
        ws.cell(row=row_idx, column=12, value=item.get("validated_at", "")[:19])
        ws.cell(row=row_idx, column=13, value=item.get("ai_ph_votes"))
        ws.cell(row=row_idx, column=14, value=item.get("corrected_ph_votes"))
        ws.cell(row=row_idx, column=15, value=item.get("votos_urna"))
        ws.cell(row=row_idx, column=16, value=item.get("novelty_note"))

    # Column widths
    widths = [6, 14, 20, 14, 8, 30, 10, 8, 12, 14, 10, 22, 10, 16, 11, 50]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"novedades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
