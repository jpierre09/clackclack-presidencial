"""Pydantic models for ClackClack API."""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# --- Database/API Models ---

class Puesto(BaseModel):
    id: str
    departamento: str
    municipio: str
    municipio_cod: str
    zona_cod: str
    puesto_cod: str
    nombre: str
    comuna: Optional[str] = None
    mesas: int
    capacidad: int
    lat: Optional[float] = None
    lon: Optional[float] = None


class E14Download(BaseModel):
    id: Optional[int] = None
    municipio_cod: str
    zona_cod: str
    puesto_cod: str
    mesa: int
    corporacion: str
    filename: str
    filepath: str
    downloaded_at: str


class E14Result(BaseModel):
    id: Optional[int] = None
    download_id: int
    municipio_cod: str
    zona_cod: str
    puesto_cod: str
    mesa: int
    corporacion: str
    votantes_e11: Optional[int] = None
    votos_urna: Optional[int] = None
    ph_votos_lista: Optional[int] = None
    ph_total_votos: Optional[int] = None
    all_sections_json: Optional[str] = None
    ocr_confidence: Optional[float] = None
    status: str = "pending"
    error_message: Optional[str] = None
    corrected_by: Optional[str] = None
    corrected_at: Optional[str] = None


class Alert(BaseModel):
    id: Optional[int] = None
    municipio_cod: str
    zona_cod: str
    puesto_cod: str
    mesa: int
    alert_type: str
    severity: str
    description: str
    sen_ph_votes: Optional[int] = None
    cam_ph_votes: Optional[int] = None
    discrepancy_pct: Optional[float] = None
    is_resolved: bool = False
    review_decision: Optional[str] = None
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[str] = None
    created_at: str


# --- API Request/Response Models ---

class DashboardSummary(BaseModel):
    total_mesas: int
    total_puestos: int
    total_municipios: int
    e14_downloaded: int
    e14_processed: int
    e14_errors: int
    alerts_total: int
    alerts_danger: int
    alerts_warning: int
    alerts_resolved: int


class HierarchyNode(BaseModel):
    code: str
    name: str
    level: str  # "municipio", "zona", "puesto", "mesa"
    alert_count: int = 0
    alert_danger: int = 0
    alert_warning: int = 0
    total_mesas: int = 0
    mesas_with_sen: int = 0
    mesas_with_cam: int = 0
    mesas_complete: int = 0
    children: Optional[list] = None
    # Mesa-level fields
    sen_ph_votes: Optional[int] = None
    cam_ph_votes: Optional[int] = None
    discrepancy_pct: Optional[float] = None
    sen_status: Optional[str] = None
    cam_status: Optional[str] = None
    ocr_confidence: Optional[float] = None


class ReclamationRequest(BaseModel):
    level: str  # "mesa", "puesto", "zona", "municipio"
    municipio_cod: str
    zona_cod: Optional[str] = None
    puesto_cod: Optional[str] = None
    mesa: Optional[int] = None
    user_name: Optional[str] = None
    user_cc: Optional[str] = None


class CorrectionRequest(BaseModel):
    ph_votos_lista: Optional[int] = None
    ph_total_votos: Optional[int] = None
    votantes_e11: Optional[int] = None
    votos_urna: Optional[int] = None


class UserSettings(BaseModel):
    user_name: str = ""
    user_cc: str = ""
