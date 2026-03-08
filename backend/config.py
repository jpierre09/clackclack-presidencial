"""Central configuration for ClackClack backend."""
import os
from pathlib import Path


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
E14_DOWNLOADS_DIR = BASE_DIR / "e14_downloads"
DB_PATH = BASE_DIR / "clackclack.db"
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
FRONTEND_PUBLIC_DIR = FRONTEND_DIR / "public"

# DIVIPOLE files
DIVIPOLE_XLSX = DATA_DIR / "DOC-20260203-WA0063..xlsx"
ANTIOQUIA_PUESTOS_JSON = DATA_DIR / "antioquia_puestos.json"
COMISIONES_XLSX = DATA_DIR / "distribucion_comisiones.xlsx"
FORMATO_DOCX = DATA_DIR / "FORMATO RECUENTO DE VOTOS .docx"

# Registraduria URLs
REGISTRADURIA_BASE_URL = "https://divulgacione14congreso.registraduria.gov.co"
REGISTRADURIA_CATALOGS_URL = f"{REGISTRADURIA_BASE_URL}/assets/temis/divipol_json"
REGISTRADURIA_PDF_URL = f"{REGISTRADURIA_BASE_URL}/assets/temis/pdf"

# Department filter: "ALL" to process all departments, or a 2-digit code (e.g. "01")
DEPT_CODE = os.getenv("DEPT_CODE", "ALL")
DEPT_NAME = os.getenv("DEPT_NAME", "TODOS")

# Corporation codes (from allCorporations.json)
CORP_SEN = "SEN"
CORP_CAM = "CAM"
CORP_CODE_MAP = {"001": "SEN", "002": "CAM"}

# Alert thresholds
ALERT_DISCREPANCY_PCT = 10.0  # >= 10% difference triggers danger alert
ALERT_LOW_CONFIDENCE = 60.0   # OCR confidence < 60% triggers warning

# Camara Antioquia projection settings
CAMARA_CURULES_ANTIOQUIA = 17
CAMARA_TIMELINE_POINTS = 80

# Pacto Historico identification patterns (case-insensitive)
PH_PATTERNS = ["PACTO", "PACT0", "PACTC", "HISTORICO", "HIST0RICO"]

# Claude OCR settings
CLAUDE_DPI = 150
CLAUDE_MAX_PAGES_SEN = 1       # Only page 5 (PACTO page) — set via page offset below
CLAUDE_MAX_PAGES_CAM = 3
CLAUDE_SEN_PACTO_PAGE = env_int("CLAUDE_SEN_PACTO_PAGE", 5)   # 1-indexed PDF page with Pacto SEN
CLAUDE_CAM_PACTO_PAGE = env_int("CLAUDE_CAM_PACTO_PAGE", 0)   # 0 = unknown, read all 3 pages

# SFTP credentials (set to enable SFTP download; if unset, poller waits)
SFTP_HOST     = os.getenv("SFTP_HOST", "")
SFTP_PORT     = env_int("SFTP_PORT", 22)
SFTP_USER     = os.getenv("SFTP_USER", "")
SFTP_PASS     = os.getenv("SFTP_PASS", "")
SFTP_KEY_PATH = os.getenv("SFTP_KEY_PATH", "")       # Path to private key file (optional)
SFTP_PATH     = os.getenv("SFTP_PATH", "/e14")       # Remote directory with PDFs

SFTP_READY = bool(SFTP_HOST and SFTP_USER and (SFTP_PASS or SFTP_KEY_PATH))

# Polling interval (seconds)
POLL_INTERVAL = 60
LOCAL_SCAN_INTERVAL = 30
ENABLE_LOCAL_INGEST = env_flag("CLACK_ENABLE_LOCAL_INGEST", True)
ENABLE_REMOTE_POLLER = env_flag("CLACK_ENABLE_REMOTE_POLLER", False)
SERVE_FRONTEND = env_flag("CLACK_SERVE_FRONTEND", False)

# Server
HOST = os.getenv("CLACK_HOST", "0.0.0.0")
PORT = env_int("PORT", env_int("CLACK_PORT", 8000))
