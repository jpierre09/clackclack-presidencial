"""Central configuration for ClackClack backend — Presidencial 2026."""
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

# Persistent storage: use PERSIST_DIR env var (e.g. /persist on Railway)
_persist = Path(os.getenv("PERSIST_DIR", "")).resolve() if os.getenv("PERSIST_DIR") else BASE_DIR
E14_DOWNLOADS_DIR = _persist / "e14_downloads"
DB_PATH = _persist / "clackclack.db"
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
FRONTEND_PUBLIC_DIR = FRONTEND_DIR / "public"

# DIVIPOLE files
DIVIPOLE_XLSX = DATA_DIR / "DOC-20260203-WA0063..xlsx"
ANTIOQUIA_PUESTOS_JSON = DATA_DIR / "antioquia_puestos.json"
COMISIONES_XLSX = DATA_DIR / "distribucion_comisiones.xlsx"
_departamental_template = next(BASE_DIR.glob("formato reclamaci*n departamental.docx"), None)
FORMATO_DOCX = _departamental_template or (DATA_DIR / "FORMATO RECUENTO DE VOTOS .docx")

# Registraduria URLs — presidencial primera vuelta 2026
REGISTRADURIA_BASE_URL = "https://divulgacione14presidencial.registraduria.gov.co"
REGISTRADURIA_CATALOGS_URL = f"{REGISTRADURIA_BASE_URL}/assets/temis/divipol_json"
REGISTRADURIA_PDF_URL = f"{REGISTRADURIA_BASE_URL}/assets/temis/pdf"

# Department filter: "ALL" to process all departments, or a 2-digit code (e.g. "01" = Antioquia)
DEPT_CODE = os.getenv("DEPT_CODE", "01")
DEPT_NAME = os.getenv("DEPT_NAME", "TODOS")

# Corporation code — presidencial primera vuelta
CORP_PRES = "PRES"

# Alert thresholds
ALERT_LOW_CONFIDENCE = 60.0   # OCR confidence < 60% triggers warning

# Claude OCR settings
CLAUDE_DPI = 150
CLAUDE_PRES_PAGE = env_int("CLAUDE_PRES_PAGE", 1)   # 1-indexed PDF page for presidencial E-14
CLAUDE_MAX_PAGES_PRES = 1

# SFTP credentials (set to enable SFTP download; if unset, poller waits)
SFTP_HOST     = os.getenv("SFTP_HOST", "")
SFTP_PORT     = env_int("SFTP_PORT", 22)
SFTP_USER     = os.getenv("SFTP_USER", "")
SFTP_PASS     = os.getenv("SFTP_PASS", "")
SFTP_KEY_PATH = os.getenv("SFTP_KEY_PATH", "")       # Path to private key file (optional)
SFTP_PATH     = os.getenv("SFTP_PATH", "/cargue")    # Remote directory with E14 cuts

SFTP_READY = bool(SFTP_HOST and SFTP_USER and (SFTP_PASS or SFTP_KEY_PATH))

# Polling intervals (seconds)
POLL_INTERVAL = 60
LOCAL_SCAN_INTERVAL = 30
SFTP_POLL_INTERVAL = env_int("SFTP_POLL_INTERVAL", 120)  # SFTP check every 2 min by default
ENABLE_LOCAL_INGEST = env_flag("CLACK_ENABLE_LOCAL_INGEST", True)
ENABLE_REMOTE_POLLER = env_flag("CLACK_ENABLE_REMOTE_POLLER", False)
SERVE_FRONTEND = env_flag("CLACK_SERVE_FRONTEND", False)

# Manual validation tool
VALIDATE_SETUP_TOKEN = os.getenv("VALIDATE_SETUP_TOKEN", "")  # required to create users
PUBLIC_EXPORT_SHARE_TOKEN = os.getenv("PUBLIC_EXPORT_SHARE_TOKEN", "")
DASHBOARD_ACCESS_TOKEN = os.getenv("DASHBOARD_ACCESS_TOKEN", "")

# Server
HOST = os.getenv("CLACK_HOST", "0.0.0.0")
PORT = env_int("PORT", env_int("CLACK_PORT", 8000))
