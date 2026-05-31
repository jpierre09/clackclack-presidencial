"""SQLite database management for ClackClack."""
import aiosqlite
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime

from backend.config import DB_PATH

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(str(DB_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _db.execute("PRAGMA busy_timeout=5000")
        await _db.execute("PRAGMA cache_size=-65536")  # 64 MB page cache
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


async def init_db():
    db = await get_db()
    await db.executescript(SCHEMA)
    await db.executescript(_SCHEMA_EXTRA)
    # Migrations: add columns that may not exist in older DBs
    for migration in _MIGRATIONS:
        try:
            await db.execute(migration)
        except Exception:
            pass  # Column already exists
    await db.commit()


_MIGRATIONS = [
    "ALTER TABLE manual_validations ADD COLUMN resolved_at TEXT",
    "ALTER TABLE manual_validations ADD COLUMN resolved_by TEXT",
    "ALTER TABLE alerts ADD COLUMN review_decision TEXT",
    "ALTER TABLE alerts ADD COLUMN reviewed_at TEXT",
    "ALTER TABLE alerts ADD COLUMN reviewed_by TEXT",
    # OCR local: firmas y recuento
    "ALTER TABLE e14_results ADD COLUMN firmas_json TEXT",
    "ALTER TABLE e14_results ADD COLUMN tiene_recuento INTEGER",
    # Encabezado OCR (municipio/zona/puesto/mesa leídos del PDF)
    "ALTER TABLE e14_results ADD COLUMN encabezado_json TEXT",
    # Prioridad de orden en el Tinder (menor = primero)
    "ALTER TABLE field_validations ADD COLUMN sort_priority INTEGER DEFAULT 99",
]

_SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS field_validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipio_cod TEXT NOT NULL,
    zona_cod TEXT NOT NULL,
    puesto_cod TEXT NOT NULL,
    mesa INTEGER NOT NULL,
    corporacion TEXT NOT NULL DEFAULT 'PRES',
    region_id TEXT NOT NULL,        -- id de la region del template (cand_1, niv_e11, etc.)
    tipo TEXT NOT NULL,             -- candidato | nivelacion | blancos_nulos | firmas | recuento
    campo_label TEXT NOT NULL,      -- nombre legible (ej: "Candidato 1 - Ivan Cepeda")
    sort_priority INTEGER DEFAULT 99, -- menor = aparece primero en el Tinder
    ocr_valor INTEGER,              -- valor detectado por OCR
    ocr_raw TEXT,                   -- texto crudo del OCR
    ocr_conf INTEGER,               -- confianza 0-100
    validated_valor INTEGER,        -- valor aprobado/corregido por el validador
    action TEXT,                    -- approved | corrected | novelty | pending
    novelty_note TEXT,
    validated_by TEXT,
    validated_at TEXT,
    UNIQUE(municipio_cod, zona_cod, puesto_cod, mesa, corporacion, region_id)
);

CREATE INDEX IF NOT EXISTS idx_field_val_location
    ON field_validations(municipio_cod, zona_cod, puesto_cod, mesa, corporacion);

CREATE INDEX IF NOT EXISTS idx_field_val_pending
    ON field_validations(action, validated_at)
    WHERE action IS NULL OR action = 'pending';
"""


SCHEMA = """
CREATE TABLE IF NOT EXISTS puestos (
    id TEXT PRIMARY KEY,
    departamento TEXT NOT NULL,
    municipio TEXT NOT NULL,
    municipio_cod TEXT NOT NULL,
    zona_cod TEXT NOT NULL,
    puesto_cod TEXT NOT NULL,
    nombre TEXT NOT NULL,
    comuna TEXT,
    mesas INTEGER NOT NULL DEFAULT 0,
    capacidad INTEGER NOT NULL DEFAULT 0,
    lat REAL,
    lon REAL
);

CREATE TABLE IF NOT EXISTS comisiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipio_cod TEXT NOT NULL,
    zona_cod TEXT NOT NULL,
    puesto_cod TEXT NOT NULL,
    puesto_nombre TEXT,
    comision_auxiliar INTEGER NOT NULL,
    nombre_comision TEXT,
    mesa_inicial INTEGER NOT NULL,
    mesa_final INTEGER NOT NULL,
    total_mesas INTEGER
);

CREATE TABLE IF NOT EXISTS e14_downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipio_cod TEXT NOT NULL,
    zona_cod TEXT NOT NULL,
    puesto_cod TEXT NOT NULL,
    mesa INTEGER NOT NULL,
    corporacion TEXT NOT NULL,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    file_size INTEGER,
    UNIQUE(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
);

CREATE TABLE IF NOT EXISTS e14_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    download_id INTEGER NOT NULL REFERENCES e14_downloads(id),
    municipio_cod TEXT NOT NULL,
    zona_cod TEXT NOT NULL,
    puesto_cod TEXT NOT NULL,
    mesa INTEGER NOT NULL,
    corporacion TEXT NOT NULL,
    votantes_e11 INTEGER,
    votos_urna INTEGER,
    ph_votos_lista INTEGER,
    ph_total_votos INTEGER,
    all_sections_json TEXT,
    ocr_confidence REAL,
    total_paginas INTEGER,
    processing_time_s REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    processed_at TEXT,
    corrected_by TEXT,
    corrected_at TEXT,
    UNIQUE(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
);

CREATE TABLE IF NOT EXISTS party_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipio_cod TEXT NOT NULL,
    zona_cod TEXT NOT NULL,
    puesto_cod TEXT NOT NULL,
    mesa INTEGER NOT NULL,
    corporacion TEXT NOT NULL,
    party_name TEXT NOT NULL,
    votes INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(municipio_cod, zona_cod, puesto_cod, mesa, corporacion, party_name)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipio_cod TEXT NOT NULL,
    zona_cod TEXT NOT NULL,
    puesto_cod TEXT NOT NULL,
    mesa INTEGER NOT NULL,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    description TEXT NOT NULL,
    sen_ph_votes INTEGER,
    cam_ph_votes INTEGER,
    discrepancy_pct REAL,
    is_resolved INTEGER DEFAULT 0,
    resolved_by TEXT,
    resolved_at TEXT,
    review_decision TEXT,
    reviewed_at TEXT,
    reviewed_by TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(municipio_cod, zona_cod, puesto_cod, mesa, alert_type)
);

CREATE TABLE IF NOT EXISTS user_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipio_cod TEXT NOT NULL,
    zona_cod TEXT NOT NULL,
    puesto_cod TEXT NOT NULL,
    mesa INTEGER NOT NULL,
    corporacion TEXT NOT NULL,
    validated_by TEXT NOT NULL,
    action TEXT NOT NULL,
    corrected_ph_votes INTEGER,
    novelty_note TEXT,
    validated_at TEXT NOT NULL,
    UNIQUE(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
);

CREATE TABLE IF NOT EXISTS queue_claims (
    municipio_cod TEXT NOT NULL,
    zona_cod TEXT NOT NULL,
    puesto_cod TEXT NOT NULL,
    mesa INTEGER NOT NULL,
    corporacion TEXT NOT NULL,
    claimed_by TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    UNIQUE(municipio_cod, zona_cod, puesto_cod, mesa, corporacion),
    UNIQUE(claimed_by)
);

CREATE INDEX IF NOT EXISTS idx_e14_results_location ON e14_results(municipio_cod, zona_cod, puesto_cod);
CREATE INDEX IF NOT EXISTS idx_alerts_location ON alerts(municipio_cod, zona_cod, puesto_cod);
CREATE INDEX IF NOT EXISTS idx_alerts_unresolved ON alerts(is_resolved) WHERE is_resolved = 0;
CREATE INDEX IF NOT EXISTS idx_e14_downloads_location ON e14_downloads(municipio_cod, zona_cod, puesto_cod);
CREATE INDEX IF NOT EXISTS idx_party_votes_corp ON party_votes(corporacion);
CREATE INDEX IF NOT EXISTS idx_party_votes_location ON party_votes(municipio_cod, zona_cod, puesto_cod, mesa);

CREATE TABLE IF NOT EXISTS crop_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    municipio_cod TEXT NOT NULL,
    zona_cod TEXT NOT NULL,
    puesto_cod TEXT NOT NULL,
    mesa INTEGER NOT NULL,
    corporacion TEXT NOT NULL,
    x0_pct REAL NOT NULL,
    y0_pct REAL NOT NULL,
    x1_pct REAL NOT NULL,
    y1_pct REAL NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
);

CREATE INDEX IF NOT EXISTS idx_alerts_location
    ON alerts(municipio_cod, zona_cod, puesto_cod, severity, is_resolved);

CREATE INDEX IF NOT EXISTS idx_results_status
    ON e14_results(status, corporacion);

CREATE INDEX IF NOT EXISTS idx_results_location
    ON e14_results(municipio_cod, zona_cod, puesto_cod, mesa, corporacion);

CREATE INDEX IF NOT EXISTS idx_downloads_location
    ON e14_downloads(municipio_cod, zona_cod, puesto_cod, mesa, corporacion);

CREATE INDEX IF NOT EXISTS idx_validations_location
    ON manual_validations(municipio_cod, zona_cod, puesto_cod, mesa, corporacion);

CREATE INDEX IF NOT EXISTS idx_validations_action
    ON manual_validations(action);

CREATE INDEX IF NOT EXISTS idx_results_processed_at
    ON e14_results(processed_at DESC) WHERE status IN ('processed','corrected');

CREATE INDEX IF NOT EXISTS idx_queue_claims_corp
    ON queue_claims(municipio_cod, zona_cod, puesto_cod, mesa, corporacion);

CREATE INDEX IF NOT EXISTS idx_alerts_review_order
    ON alerts(alert_type, is_resolved, review_decision, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_pending
    ON alerts(alert_type, created_at DESC)
    WHERE is_resolved = 0 AND review_decision IS NULL;

CREATE INDEX IF NOT EXISTS idx_e14_results_download_id
    ON e14_results(download_id);

CREATE INDEX IF NOT EXISTS idx_alerts_full_location
    ON alerts(municipio_cod, zona_cod, puesto_cod, mesa);
"""


# --- CRUD Operations ---
_FORMULA_WORD_RE = re.compile(r"[^A-Z0-9 ]+")
_SPACE_RE = re.compile(r"\s+")


def _normalize_formula_name(raw_name: str) -> str:
    """Normalize a presidential candidate formula name."""
    text = (raw_name or "").strip().upper()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFD", text)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = _FORMULA_WORD_RE.sub(" ", normalized)
    return _SPACE_RE.sub(" ", normalized).strip()


def _to_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    digits = re.sub(r"[^0-9-]", "", str(value))
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def _extract_formula_votes(all_sections_json: str | None) -> dict[str, int]:
    """Extract votes per presidential candidate formula from stored JSON."""
    if not all_sections_json:
        return {}
    try:
        sections = json.loads(all_sections_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(sections, list):
        return {}

    votes_by_formula: defaultdict[str, int] = defaultdict(int)
    for section in sections:
        if not isinstance(section, dict):
            continue
        if section.get("tipo") not in ("formula", "partido"):
            continue
        # Use candidato_presidente if available, else nombre
        name = (
            section.get("candidato_presidente")
            or section.get("nombre")
            or ""
        )
        formula_name = _normalize_formula_name(str(name))
        if not formula_name:
            continue
        votes = _to_int(section.get("total_votos"))
        if votes <= 0:
            votes = _to_int(section.get("votos_lista"))
        if votes < 0:
            votes = 0
        votes_by_formula[formula_name] += votes
    return dict(votes_by_formula)


async def _refresh_party_votes(db: aiosqlite.Connection, data: dict) -> None:
    mun = data["municipio_cod"]
    zona = data["zona_cod"]
    puesto = data["puesto_cod"]
    mesa = data["mesa"]
    corp = data["corporacion"]
    status = data.get("status", "")

    await db.execute(
        """DELETE FROM party_votes
           WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
             AND mesa = ? AND corporacion = ?""",
        (mun, zona, puesto, mesa, corp),
    )

    if status not in {"processed", "corrected"}:
        return

    party_votes = _extract_formula_votes(data.get("all_sections_json"))
    if not party_votes:
        return

    updated_at = datetime.now().isoformat()
    for party_name, votes in party_votes.items():
        await db.execute(
            """INSERT INTO party_votes
            (municipio_cod, zona_cod, puesto_cod, mesa, corporacion, party_name, votes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, corporacion, party_name)
            DO UPDATE SET votes = excluded.votes, updated_at = excluded.updated_at""",
            (mun, zona, puesto, mesa, corp, party_name, votes, updated_at),
        )


async def insert_puesto(data: dict):
    db = await get_db()
    await db.execute(
        """INSERT OR IGNORE INTO puestos
        (id, departamento, municipio, municipio_cod, zona_cod, puesto_cod,
         nombre, comuna, mesas, capacidad, lat, lon)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data["id"], data["departamento"], data["municipio"],
         data["municipio_cod"], data["zona_cod"], data["puesto_cod"],
         data["nombre"], data.get("comuna"), data["mesas"],
         data.get("capacidad", 0), data.get("lat"), data.get("lon"))
    )


async def insert_comision(data: dict):
    db = await get_db()
    await db.execute(
        """INSERT OR IGNORE INTO comisiones
        (municipio_cod, zona_cod, puesto_cod, puesto_nombre,
         comision_auxiliar, nombre_comision, mesa_inicial, mesa_final, total_mesas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data["municipio_cod"], data["zona_cod"], data["puesto_cod"],
         data.get("puesto_nombre"), data["comision_auxiliar"],
         data.get("nombre_comision"), data["mesa_inicial"],
         data["mesa_final"], data.get("total_mesas"))
    )


async def insert_download(data: dict) -> int:
    db = await get_db()
    await db.execute(
        """INSERT INTO e14_downloads
        (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
         filename, filepath, downloaded_at, file_size)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
        DO UPDATE SET
            filename = excluded.filename,
            filepath = excluded.filepath,
            downloaded_at = excluded.downloaded_at,
            file_size = excluded.file_size""",
        (
            data["municipio_cod"],
            data["zona_cod"],
            data["puesto_cod"],
            data["mesa"],
            data["corporacion"],
            data["filename"],
            data["filepath"],
            data["downloaded_at"],
            data.get("file_size"),
        ),
    )
    await db.commit()
    row = await db.execute_fetchall(
        """SELECT id FROM e14_downloads
           WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
             AND mesa = ? AND corporacion = ?""",
        (
            data["municipio_cod"],
            data["zona_cod"],
            data["puesto_cod"],
            data["mesa"],
            data["corporacion"],
        ),
    )
    return row[0][0]


async def insert_result(data: dict) -> int:
    db = await get_db()
    await db.execute(
        """INSERT INTO e14_results
        (download_id, municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
         votantes_e11, votos_urna, ph_votos_lista, ph_total_votos,
         all_sections_json, ocr_confidence, total_paginas, processing_time_s,
         status, error_message, processed_at, firmas_json, tiene_recuento,
         encabezado_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
        DO UPDATE SET
            download_id = excluded.download_id,
            votantes_e11 = excluded.votantes_e11,
            votos_urna = excluded.votos_urna,
            ph_votos_lista = excluded.ph_votos_lista,
            ph_total_votos = excluded.ph_total_votos,
            all_sections_json = excluded.all_sections_json,
            ocr_confidence = excluded.ocr_confidence,
            total_paginas = excluded.total_paginas,
            processing_time_s = excluded.processing_time_s,
            status = excluded.status,
            error_message = excluded.error_message,
            processed_at = excluded.processed_at,
            firmas_json = excluded.firmas_json,
            tiene_recuento = excluded.tiene_recuento,
            encabezado_json = excluded.encabezado_json
        WHERE e14_results.status NOT IN ('processed', 'corrected')""",
        (
            data["download_id"],
            data["municipio_cod"],
            data["zona_cod"],
            data["puesto_cod"],
            data["mesa"],
            data["corporacion"],
            data.get("votantes_e11"),
            data.get("votos_urna"),
            data.get("ph_votos_lista"),
            data.get("ph_total_votos"),
            data.get("all_sections_json"),
            data.get("ocr_confidence"),
            data.get("total_paginas"),
            data.get("processing_time_s"),
            data["status"],
            data.get("error_message"),
            data.get("processed_at"),
            data.get("firmas_json"),
            data.get("tiene_recuento"),
            data.get("encabezado_json"),
        ),
    )

    await _refresh_party_votes(db, data)

    # Sembrar campo-a-campo para el Tinder (solo en resultados procesados)
    if data.get("status") == "processed" and data.get("all_sections_json"):
        await seed_field_validations(
            municipio_cod=data["municipio_cod"],
            zona_cod=data["zona_cod"],
            puesto_cod=data["puesto_cod"],
            mesa=data["mesa"],
            corporacion=data["corporacion"],
            sections_json=data.get("all_sections_json", "[]"),
            ocr_results={
                "votantes_e11":   data.get("votantes_e11"),
                "votos_urna":     data.get("votos_urna"),
                "firmas":         data.get("_firmas_list", []),
                "tiene_recuento": data.get("_tiene_recuento"),
            },
        )

    await db.commit()
    row = await db.execute_fetchall(
        """SELECT id FROM e14_results
           WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
             AND mesa = ? AND corporacion = ?""",
        (
            data["municipio_cod"],
            data["zona_cod"],
            data["puesto_cod"],
            data["mesa"],
            data["corporacion"],
        ),
    )
    return row[0][0]


async def rebuild_party_votes_index(force: bool = False) -> dict:
    db = await get_db()
    existing_rows = await db.execute_fetchall("SELECT COUNT(*) AS total FROM party_votes")
    existing_total = int(existing_rows[0]["total"] or 0)
    if existing_total > 0 and not force:
        return {"rebuilt": False, "rows": existing_total}

    if force:
        await db.execute("DELETE FROM party_votes")

    result_rows = await db.execute_fetchall(
        """SELECT municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
                  status, all_sections_json
           FROM e14_results"""
    )
    for row in result_rows:
        await _refresh_party_votes(
            db,
            {
                "municipio_cod": row["municipio_cod"],
                "zona_cod": row["zona_cod"],
                "puesto_cod": row["puesto_cod"],
                "mesa": int(row["mesa"]),
                "corporacion": row["corporacion"],
                "status": row["status"],
                "all_sections_json": row["all_sections_json"],
            },
        )
    await db.commit()

    rebuilt_rows = await db.execute_fetchall("SELECT COUNT(*) AS total FROM party_votes")
    return {"rebuilt": True, "rows": int(rebuilt_rows[0]["total"] or 0)}


async def upsert_alert(data: dict) -> int:
    db = await get_db()
    await db.execute(
        """INSERT INTO alerts
        (municipio_cod, zona_cod, puesto_cod, mesa, alert_type,
         severity, description, sen_ph_votes, cam_ph_votes,
         discrepancy_pct, is_resolved, review_decision,
         reviewed_at, reviewed_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, alert_type)
        DO UPDATE SET
            severity = excluded.severity,
            description = excluded.description,
            sen_ph_votes = excluded.sen_ph_votes,
            cam_ph_votes = excluded.cam_ph_votes,
            discrepancy_pct = excluded.discrepancy_pct,
            is_resolved = CASE
                WHEN alerts.sen_ph_votes IS excluded.sen_ph_votes
                 AND alerts.cam_ph_votes IS excluded.cam_ph_votes
                 AND alerts.discrepancy_pct IS excluded.discrepancy_pct
                 AND alerts.review_decision = 'false_alert'
                THEN 1
                ELSE 0
            END,
            resolved_by = CASE
                WHEN alerts.sen_ph_votes IS excluded.sen_ph_votes
                 AND alerts.cam_ph_votes IS excluded.cam_ph_votes
                 AND alerts.discrepancy_pct IS excluded.discrepancy_pct
                 AND alerts.review_decision = 'false_alert'
                THEN alerts.resolved_by
                ELSE NULL
            END,
            resolved_at = CASE
                WHEN alerts.sen_ph_votes IS excluded.sen_ph_votes
                 AND alerts.cam_ph_votes IS excluded.cam_ph_votes
                 AND alerts.discrepancy_pct IS excluded.discrepancy_pct
                 AND alerts.review_decision = 'false_alert'
                THEN alerts.resolved_at
                ELSE NULL
            END,
            review_decision = CASE
                WHEN alerts.sen_ph_votes IS excluded.sen_ph_votes
                 AND alerts.cam_ph_votes IS excluded.cam_ph_votes
                 AND alerts.discrepancy_pct IS excluded.discrepancy_pct
                THEN alerts.review_decision
                ELSE NULL
            END,
            reviewed_at = CASE
                WHEN alerts.sen_ph_votes IS excluded.sen_ph_votes
                 AND alerts.cam_ph_votes IS excluded.cam_ph_votes
                 AND alerts.discrepancy_pct IS excluded.discrepancy_pct
                THEN alerts.reviewed_at
                ELSE NULL
            END,
            reviewed_by = CASE
                WHEN alerts.sen_ph_votes IS excluded.sen_ph_votes
                 AND alerts.cam_ph_votes IS excluded.cam_ph_votes
                 AND alerts.discrepancy_pct IS excluded.discrepancy_pct
                THEN alerts.reviewed_by
                ELSE NULL
            END,
            created_at = excluded.created_at""",
        (
            data["municipio_cod"],
            data["zona_cod"],
            data["puesto_cod"],
            data["mesa"],
            data["alert_type"],
            data["severity"],
            data["description"],
            data.get("sen_ph_votes"),
            data.get("cam_ph_votes"),
            data.get("discrepancy_pct"),
            None,
            None,
            None,
            data["created_at"],
        ),
    )
    await db.commit()
    row = await db.execute_fetchall(
        """SELECT id FROM alerts
           WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
             AND mesa = ? AND alert_type = ?""",
        (
            data["municipio_cod"],
            data["zona_cod"],
            data["puesto_cod"],
            data["mesa"],
            data["alert_type"],
        ),
    )
    return row[0][0]


async def get_dashboard_summary() -> dict:
    db = await get_db()
    row = await db.execute_fetchall("""
        SELECT
            (SELECT COUNT(*) * 2 FROM puestos WHERE departamento='ANTIOQUIA') as total_mesas_approx,
            (SELECT SUM(mesas) FROM puestos WHERE departamento='ANTIOQUIA') as total_mesas,
            (SELECT COUNT(*) FROM puestos WHERE departamento='ANTIOQUIA') as total_puestos,
            (SELECT COUNT(DISTINCT municipio_cod) FROM puestos WHERE departamento='ANTIOQUIA') as total_municipios,
            (SELECT COUNT(*) FROM e14_downloads) as e14_downloaded,
            (SELECT COUNT(*) FROM e14_results WHERE status='processed' OR status='corrected') as e14_processed,
            (SELECT COUNT(*) FROM e14_results WHERE status='error') as e14_errors,
            (SELECT COUNT(*) FROM alerts WHERE is_resolved=0) as alerts_total,
            (SELECT COUNT(*) FROM alerts WHERE is_resolved=0 AND severity='danger') as alerts_danger,
            (SELECT COUNT(*) FROM alerts WHERE is_resolved=0 AND severity='warning') as alerts_warning,
            (SELECT COUNT(*) FROM alerts WHERE is_resolved=1) as alerts_resolved,
            (SELECT COUNT(*) FROM manual_validations WHERE novelty_note IS NOT NULL AND novelty_note != '') as novedades_count
    """)
    r = row[0]
    return {
        "total_mesas": r[1] or 0,
        "total_puestos": r[2] or 0,
        "total_municipios": r[3] or 0,
        "e14_downloaded": r[4] or 0,
        "e14_processed": r[5] or 0,
        "e14_errors": r[6] or 0,
        "alerts_total": r[7] or 0,
        "alerts_danger": r[8] or 0,
        "alerts_warning": r[9] or 0,
        "alerts_resolved": r[10] or 0,
        "novedades_count": r[11] or 0,
    }


async def get_hierarchy_with_alerts() -> list[dict]:
    """Like get_hierarchy but restricted to municipios that have active alerts.
    Used for the default (no-filter) dashboard view — fast and focused.
    """
    db = await get_db()
    # Top 10 municipios por cantidad de alertas activas
    alert_muns = await db.execute_fetchall(
        """SELECT municipio_cod, COUNT(*) as cnt
           FROM alerts WHERE is_resolved = 0
           GROUP BY municipio_cod
           ORDER BY cnt DESC LIMIT 10"""
    )
    mun_codes = [r["municipio_cod"] for r in alert_muns]
    if not mun_codes:
        return []
    results = []
    for mun_cod in mun_codes:
        rows = await get_hierarchy(mun_cod)
        results.extend(rows)
    results.sort(key=lambda m: -(m.get("alerts_danger", 0) + m.get("alerts_warning", 0)))
    return results


async def get_hierarchy(municipio_cod: str | None = None) -> list[dict]:
    """Get hierarchical data: municipio > zona > puesto > mesas.

    Replaces the old N+1 nested loop (9 000+ queries) with 3 flat queries
    that are then assembled into the tree in Python.
    """
    db = await get_db()
    puesto_params: list[object] = []
    mesa_params: list[object] = []
    alert_params: list[object] = []
    puesto_filter = ""
    mesa_filter = ""
    alert_filter = ""

    if municipio_cod:
        puesto_filter = " AND p.municipio_cod = ?"
        mesa_filter = " WHERE d2.municipio_cod = ?"
        alert_filter = " AND municipio_cod = ?"
        puesto_params.append(municipio_cod)
        mesa_params.append(municipio_cod)
        alert_params.append(municipio_cod)

    # ── Query 1: all puestos for Antioquia with per-puesto alert count ─────────
    puesto_rows = await db.execute_fetchall(f"""
        SELECT
            p.municipio_cod, p.municipio,
            p.zona_cod, p.puesto_cod, p.nombre, p.mesas, p.lat, p.lon,
            COUNT(DISTINCT a.id) AS alert_count
        FROM puestos p
        LEFT JOIN alerts a ON a.municipio_cod = p.municipio_cod
            AND a.zona_cod = p.zona_cod AND a.puesto_cod = p.puesto_cod
            AND a.is_resolved = 0
        WHERE p.departamento = 'ANTIOQUIA'{puesto_filter}
        GROUP BY p.municipio_cod, p.zona_cod, p.puesto_cod
        ORDER BY p.municipio_cod, p.zona_cod, p.puesto_cod
    """, puesto_params)

    # ── Query 2: all mesas data flat (one row per mesa, PRES only) ────────────
    mesa_rows = await db.execute_fetchall(f"""
        SELECT
            d.municipio_cod, d.zona_cod, d.puesto_cod, d.mesa,
            rp.ph_total_votos AS pres_votes,
            rp.status AS pres_status,
            rp.ocr_confidence AS pres_conf,
            a.alert_type, a.severity, a.discrepancy_pct,
            CASE WHEN mv_n.id IS NOT NULL THEN 1 ELSE 0 END AS has_novelty
        FROM (
            SELECT DISTINCT d2.municipio_cod, d2.zona_cod, d2.puesto_cod, d2.mesa
            FROM e14_downloads d2
            JOIN puestos p2 ON p2.municipio_cod = d2.municipio_cod
                AND p2.zona_cod = d2.zona_cod AND p2.puesto_cod = d2.puesto_cod
                AND p2.departamento = 'ANTIOQUIA'
            {mesa_filter}
        ) d
        LEFT JOIN e14_results rp ON rp.municipio_cod = d.municipio_cod
            AND rp.zona_cod = d.zona_cod AND rp.puesto_cod = d.puesto_cod
            AND rp.mesa = d.mesa AND rp.corporacion = 'PRES'
        LEFT JOIN alerts a ON a.municipio_cod = d.municipio_cod
            AND a.zona_cod = d.zona_cod AND a.puesto_cod = d.puesto_cod
            AND a.mesa = d.mesa AND a.is_resolved = 0 AND a.severity != 'info'
        LEFT JOIN manual_validations mv_n ON mv_n.municipio_cod = d.municipio_cod
            AND mv_n.zona_cod = d.zona_cod AND mv_n.puesto_cod = d.puesto_cod
            AND mv_n.mesa = d.mesa
            AND mv_n.novelty_note IS NOT NULL AND mv_n.novelty_note != ''
        ORDER BY d.municipio_cod, d.zona_cod, d.puesto_cod, d.mesa
    """, mesa_params)

    # ── Query 3: municipio-level danger / warning counts ───────────────────────
    alert_rows = await db.execute_fetchall(f"""
        SELECT municipio_cod,
            COUNT(DISTINCT CASE WHEN severity = 'danger'  THEN id END) AS alerts_danger,
            COUNT(DISTINCT CASE WHEN severity = 'warning' THEN id END) AS alerts_warning
        FROM alerts
        WHERE is_resolved = 0{alert_filter}
        GROUP BY municipio_cod
    """, alert_params)
    mun_alerts: dict[str, dict] = {r["municipio_cod"]: dict(r) for r in alert_rows}

    # ── Assemble tree in Python ────────────────────────────────────────────────
    mesas_by_puesto: dict[tuple, list] = defaultdict(list)
    for r in mesa_rows:
        key = (r["municipio_cod"], r["zona_cod"], r["puesto_cod"])
        mesas_by_puesto[key].append({
            "mesa": r["mesa"],
            "pres_votes": r["pres_votes"],
            "pres_status": r["pres_status"],
            "pres_conf": r["pres_conf"],
            "alert_type": r["alert_type"], "severity": r["severity"],
            "discrepancy_pct": r["discrepancy_pct"],
            "has_novelty": r["has_novelty"],
        })

    puestos_by_zona: dict[tuple, list] = defaultdict(list)
    for r in puesto_rows:
        pkey = (r["municipio_cod"], r["zona_cod"], r["puesto_cod"])
        zkey = (r["municipio_cod"], r["zona_cod"])
        puestos_by_zona[zkey].append({
            "puesto_cod": r["puesto_cod"], "nombre": r["nombre"],
            "mesas": r["mesas"], "lat": r["lat"], "lon": r["lon"],
            "alert_count": r["alert_count"],
            "mesas_data": mesas_by_puesto.get(pkey, []),
        })

    seen_zonas: set[tuple] = set()
    zonas_by_mun: dict[str, list] = defaultdict(list)
    for r in puesto_rows:
        zkey = (r["municipio_cod"], r["zona_cod"])
        if zkey in seen_zonas:
            continue
        seen_zonas.add(zkey)
        puestos = puestos_by_zona[zkey]
        zonas_by_mun[r["municipio_cod"]].append({
            "zona_cod": r["zona_cod"],
            "total_mesas": sum(p["mesas"] for p in puestos),
            "alert_count": sum(p["alert_count"] for p in puestos),
            "puestos": puestos,
        })

    seen_muns: set[str] = set()
    municipios = []
    for r in puesto_rows:
        mun_cod = r["municipio_cod"]
        if mun_cod in seen_muns:
            continue
        seen_muns.add(mun_cod)
        zonas = zonas_by_mun[mun_cod]
        ac = mun_alerts.get(mun_cod, {})
        municipios.append({
            "municipio_cod": mun_cod,
            "municipio": r["municipio"],
            "total_mesas": sum(z["total_mesas"] for z in zonas),
            "alerts_danger": int(ac.get("alerts_danger", 0) or 0),
            "alerts_warning": int(ac.get("alerts_warning", 0) or 0),
            "zonas": zonas,
        })

    municipios.sort(key=lambda item: (
        -(item["alerts_danger"] + item["alerts_warning"]),
        -item["alerts_danger"],
        item["municipio"],
    ))
    return municipios


async def get_municipio_options() -> list[dict]:
    """Return lightweight municipio options for filter selects."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """
        SELECT municipio_cod, MAX(municipio) AS municipio
        FROM puestos
        WHERE departamento = 'ANTIOQUIA'
        GROUP BY municipio_cod
        ORDER BY municipio
        """
    )
    return [
        {
            "municipio_cod": row["municipio_cod"],
            "municipio": row["municipio"],
        }
        for row in rows
    ]


async def get_alerts(municipio_cod: str = None, resolved: bool = False) -> list[dict]:
    db = await get_db()
    query = """
        SELECT a.*, p.municipio, p.nombre as puesto_nombre
        FROM alerts a
        JOIN puestos p ON p.municipio_cod = a.municipio_cod
            AND p.zona_cod = a.zona_cod AND p.puesto_cod = a.puesto_cod
        WHERE a.is_resolved = ?
    """
    params = [1 if resolved else 0]
    if municipio_cod:
        query += " AND a.municipio_cod = ?"
        params.append(municipio_cod)
    query += " ORDER BY a.created_at DESC"
    rows = await db.execute_fetchall(query, params)
    return [dict(r) for r in rows]


def _build_alert_review_item(row: dict) -> dict:
    mun = row["municipio_cod"]
    zona = row["zona_cod"]
    puesto = row["puesto_cod"]
    mesa = row["mesa"]

    pres_data = {
        "corp": "PRES",
        "validated_votes": row.get("pres_validated_votes"),
        "ai_votes": row.get("pres_ai_votes"),
        "votos_urna": row.get("pres_votos_urna"),
        "ocr_confidence": row.get("pres_ocr_confidence"),
        "result_status": row.get("pres_result_status"),
        "validation_action": row.get("pres_validation_action"),
        "validated_by": row.get("pres_validated_by"),
        "validated_at": row.get("pres_validated_at"),
        "corrected_ph_votes": row.get("pres_corrected_ph_votes"),
        "screenshot_path": f"/api/validar/screenshot/{mun}/{zona}/{puesto}/{mesa}/PRES",
    }

    return {
        "id": row["id"],
        "municipio_cod": mun,
        "zona_cod": zona,
        "puesto_cod": puesto,
        "mesa": mesa,
        "municipio": row["municipio"],
        "puesto_nombre": row["puesto_nombre"],
        "alert_type": row["alert_type"],
        "severity": row["severity"],
        "description": row["description"],
        "discrepancy_pct": row["discrepancy_pct"],
        "vote_gap": None,
        "is_resolved": row["is_resolved"],
        "created_at": row["created_at"],
        "review_decision": row["review_decision"],
        "reviewed_at": row["reviewed_at"],
        "reviewed_by": row["reviewed_by"],
        "resolved_at": row["resolved_at"],
        "resolved_by": row["resolved_by"],
        "pres": pres_data,
    }


async def get_alert_review_items(
    municipio_cod: str | None = None,
    reviewed: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    db = await get_db()
    query = """
        SELECT
            a.id,
            a.municipio_cod,
            a.zona_cod,
            a.puesto_cod,
            a.mesa,
            a.alert_type,
            a.severity,
            a.description,
            a.discrepancy_pct,
            a.is_resolved,
            a.created_at,
            a.review_decision,
            a.reviewed_at,
            a.reviewed_by,
            a.resolved_at,
            a.resolved_by,
            p.municipio,
            p.nombre AS puesto_nombre,
            COALESCE(pres_mv.corrected_ph_votes, pres_r.ph_total_votos) AS pres_validated_votes,
            pres_r.ph_total_votos AS pres_ai_votes,
            pres_r.votos_urna AS pres_votos_urna,
            pres_r.ocr_confidence AS pres_ocr_confidence,
            pres_r.status AS pres_result_status,
            pres_mv.action AS pres_validation_action,
            pres_mv.validated_by AS pres_validated_by,
            pres_mv.validated_at AS pres_validated_at,
            pres_mv.corrected_ph_votes AS pres_corrected_ph_votes
        FROM alerts a
        LEFT JOIN puestos p
            ON p.municipio_cod = a.municipio_cod
            AND p.zona_cod = a.zona_cod
            AND p.puesto_cod = a.puesto_cod
        LEFT JOIN e14_results pres_r
            ON pres_r.municipio_cod = a.municipio_cod
            AND pres_r.zona_cod = a.zona_cod
            AND pres_r.puesto_cod = a.puesto_cod
            AND pres_r.mesa = a.mesa
            AND pres_r.corporacion = 'PRES'
        LEFT JOIN manual_validations pres_mv
            ON pres_mv.municipio_cod = a.municipio_cod
            AND pres_mv.zona_cod = a.zona_cod
            AND pres_mv.puesto_cod = a.puesto_cod
            AND pres_mv.mesa = a.mesa
            AND pres_mv.corporacion = 'PRES'
        WHERE 1=1
    """
    params: list[str] = []
    if reviewed:
        query += " AND a.review_decision IS NOT NULL"
    else:
        query += " AND a.is_resolved = 0 AND a.review_decision IS NULL"
    if municipio_cod:
        query += " AND a.municipio_cod = ?"
        params.append(municipio_cod)
    query += " ORDER BY a.created_at DESC, COALESCE(a.discrepancy_pct, 0) DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = await db.execute_fetchall(query, params)
    return [_build_alert_review_item(dict(row)) for row in rows]


async def get_alert_review_summary(municipio_cod: str | None = None) -> dict[str, int]:
    db = await get_db()
    query = """
        SELECT
            SUM(CASE WHEN a.review_decision = 'real_alert' THEN 1 ELSE 0 END) AS real_alert,
            SUM(CASE WHEN a.review_decision = 'false_alert' THEN 1 ELSE 0 END) AS false_alert,
            SUM(CASE WHEN a.is_resolved = 0 AND a.review_decision IS NULL THEN 1 ELSE 0 END) AS pending
        FROM alerts a
        WHERE 1=1
    """
    params: list[str] = []
    if municipio_cod:
        query += " AND a.municipio_cod = ?"
        params.append(municipio_cod)

    rows = await db.execute_fetchall(query, params)
    row = dict(rows[0]) if rows else {}
    real_alert = int(row.get("real_alert") or 0)
    false_alert = int(row.get("false_alert") or 0)
    pending = int(row.get("pending") or 0)
    return {
        "real_alert": real_alert,
        "false_alert": false_alert,
        "pending": pending,
        "reviewed_total": real_alert + false_alert,
    }


async def bulk_review_pending_alerts(
    decision: str,
    reviewed_by: str = "dashboard_bulk",
    municipio_cod: str | None = None,
) -> dict[str, int]:
    db = await get_db()
    now = datetime.now().isoformat()
    is_false_alert = decision == "false_alert"

    query = """
        UPDATE alerts
        SET review_decision = ?,
            reviewed_at = ?,
            reviewed_by = ?,
            is_resolved = ?,
            resolved_at = ?,
            resolved_by = ?
        WHERE is_resolved = 0
          AND review_decision IS NULL
    """
    params: list[object] = [
        decision,
        now,
        reviewed_by,
        1 if is_false_alert else 0,
        now if is_false_alert else None,
        reviewed_by if is_false_alert else None,
    ]
    if municipio_cod:
        query += " AND municipio_cod = ?"
        params.append(municipio_cod)

    await db.execute(query, params)
    await db.commit()
    changed_row = await db.execute_fetchall("SELECT changes() AS n")
    summary = await get_alert_review_summary(municipio_cod)
    return {
        "updated": int(changed_row[0]["n"] if changed_row else 0),
        **summary,
    }


async def review_alert(alert_id: int, decision: str, reviewed_by: str = "dashboard") -> bool:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id FROM alerts WHERE id = ?",
        (alert_id,),
    )
    if not rows:
        return False

    now = datetime.now().isoformat()
    is_false_alert = decision == "false_alert"
    await db.execute(
        """
        UPDATE alerts
        SET review_decision = ?,
            reviewed_at = ?,
            reviewed_by = ?,
            is_resolved = ?,
            resolved_at = ?,
            resolved_by = ?
        WHERE id = ?
        """,
        (
            decision,
            now,
            reviewed_by,
            1 if is_false_alert else 0,
            now if is_false_alert else None,
            reviewed_by if is_false_alert else None,
            alert_id,
        ),
    )
    await db.commit()
    return True


async def get_mesa_detail(mun: str, zona: str, puesto: str, mesa: int) -> dict:
    db = await get_db()
    # Get results
    results = await db.execute_fetchall("""
        SELECT r.*, d.filename, d.filepath
        FROM e14_results r
        JOIN e14_downloads d ON d.id = r.download_id
        WHERE r.municipio_cod = ? AND r.zona_cod = ? AND r.puesto_cod = ? AND r.mesa = ?
    """, (mun, zona, puesto, mesa))
    # Get alerts
    alerts = await db.execute_fetchall("""
        SELECT * FROM alerts
        WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ? AND mesa = ?
    """, (mun, zona, puesto, mesa))
    # Get puesto info
    puesto_info = await db.execute_fetchall("""
        SELECT * FROM puestos
        WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
    """, (mun, zona, puesto))

    return {
        "results": [dict(r) for r in results],
        "alerts": [dict(a) for a in alerts],
        "puesto": dict(puesto_info[0]) if puesto_info else None,
    }


async def update_result_correction(mun: str, zona: str, puesto: str, mesa: int,
                                    corp: str, data: dict):
    db = await get_db()
    from datetime import datetime
    await db.execute("""
        UPDATE e14_results SET
            ph_votos_lista = COALESCE(?, ph_votos_lista),
            ph_total_votos = COALESCE(?, ph_total_votos),
            votantes_e11 = COALESCE(?, votantes_e11),
            votos_urna = COALESCE(?, votos_urna),
            status = 'corrected',
            corrected_at = ?
        WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
            AND mesa = ? AND corporacion = ?
    """, (data.get("ph_votos_lista"), data.get("ph_total_votos"),
          data.get("votantes_e11"), data.get("votos_urna"),
          datetime.now().isoformat(),
          mun, zona, puesto, mesa, corp))
    await db.commit()


async def get_comision_for_mesa(mun: str, zona: str, puesto: str, mesa: int) -> dict | None:
    db = await get_db()
    rows = await db.execute_fetchall("""
        SELECT * FROM comisiones
        WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
            AND mesa_inicial <= ? AND mesa_final >= ?
        LIMIT 1
    """, (mun, zona, puesto, mesa, mesa))
    return dict(rows[0]) if rows else None


async def get_alerts_for_reclamation(level: str, mun: str,
                                      zona: str = None, puesto: str = None,
                                      mesa: int | None = None) -> list[dict]:
    db = await get_db()
    query = """
        SELECT a.*, p.municipio, p.nombre as puesto_nombre,
            rp.ph_total_votos as pres_votes_actual
        FROM alerts a
        JOIN puestos p ON p.municipio_cod = a.municipio_cod
            AND p.zona_cod = a.zona_cod AND p.puesto_cod = a.puesto_cod
        LEFT JOIN e14_results rp ON rp.municipio_cod = a.municipio_cod
            AND rp.zona_cod = a.zona_cod AND rp.puesto_cod = a.puesto_cod
            AND rp.mesa = a.mesa AND rp.corporacion = 'PRES'
        WHERE a.is_resolved = 0
            AND a.municipio_cod = ?
    """
    params = [mun]
    if level in {"zona", "puesto", "mesa"} and zona:
        query += " AND a.zona_cod = ?"
        params.append(zona)
    if level in {"puesto", "mesa"} and puesto:
        query += " AND a.puesto_cod = ?"
        params.append(puesto)
    if level == "mesa" and mesa is not None:
        query += " AND a.mesa = ?"
        params.append(mesa)
    query += " ORDER BY a.zona_cod, a.puesto_cod, a.mesa"
    rows = await db.execute_fetchall(query, params)
    return [dict(r) for r in rows]


async def get_all_alerts_for_reclamation() -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        """
        SELECT a.*, p.municipio, p.nombre as puesto_nombre,
            rp.ph_total_votos as pres_votes_actual
        FROM alerts a
        JOIN puestos p ON p.municipio_cod = a.municipio_cod
            AND p.zona_cod = a.zona_cod AND p.puesto_cod = a.puesto_cod
        LEFT JOIN e14_results rp ON rp.municipio_cod = a.municipio_cod
            AND rp.zona_cod = a.zona_cod AND rp.puesto_cod = a.puesto_cod
            AND rp.mesa = a.mesa AND rp.corporacion = 'PRES'
        WHERE a.is_resolved = 0
        ORDER BY p.municipio, a.zona_cod, a.puesto_cod, a.mesa
        """
    )
    return [dict(r) for r in rows]


async def get_map_data() -> list[dict]:
    """Get puesto-level data with coordinates and alert counts for map."""
    db = await get_db()
    rows = await db.execute_fetchall("""
        SELECT
            p.id, p.municipio, p.municipio_cod, p.zona_cod, p.puesto_cod,
            p.nombre, p.mesas, p.lat, p.lon,
            COUNT(DISTINCT CASE WHEN a.severity='danger' AND a.is_resolved=0 THEN a.id END) as danger_count,
            COUNT(DISTINCT CASE WHEN a.severity='warning' AND a.is_resolved=0 THEN a.id END) as warning_count,
            COUNT(DISTINCT CASE WHEN a.severity='info' AND a.is_resolved=0 THEN a.id END) as novelty_count
        FROM puestos p
        LEFT JOIN alerts a ON a.municipio_cod = p.municipio_cod
            AND a.zona_cod = p.zona_cod AND a.puesto_cod = p.puesto_cod
        WHERE p.departamento = 'ANTIOQUIA' AND p.lat IS NOT NULL
        GROUP BY p.id
        HAVING danger_count > 0 OR warning_count > 0 OR novelty_count > 0
    """)
    return [dict(r) for r in rows]


async def get_pres_live_projection() -> dict:
    """Return live vote totals per presidential formula from processed PRES mesas."""
    db = await get_db()

    mesas_row = await db.execute_fetchall(
        "SELECT COALESCE(SUM(mesas), 0) AS total_mesas FROM puestos WHERE departamento = 'ANTIOQUIA'"
    )
    total_mesas = int(mesas_row[0]["total_mesas"] or 0)

    processed_row = await db.execute_fetchall(
        "SELECT COUNT(*) AS total FROM e14_results WHERE corporacion = 'PRES' AND status IN ('processed', 'corrected')"
    )
    mesas_reportadas = int(processed_row[0]["total"] or 0)

    formula_rows = await db.execute_fetchall(
        """SELECT party_name, SUM(votes) AS votes
           FROM party_votes
           WHERE corporacion = 'PRES'
           GROUP BY party_name
           HAVING SUM(votes) > 0
           ORDER BY votes DESC, party_name"""
    )

    total_votes = 0
    formulas_payload = []
    for row in formula_rows:
        votes = int(row["votes"] or 0)
        total_votes += votes
        formulas_payload.append({
            "formula_name": row["party_name"],
            "votes": votes,
        })

    for f in formulas_payload:
        f["vote_share_pct"] = round(f["votes"] / total_votes * 100, 2) if total_votes else 0.0

    projection_scale = (total_mesas / mesas_reportadas) if mesas_reportadas > 0 else 1.0

    return {
        "mesas_total": total_mesas,
        "mesas_reportadas": mesas_reportadas,
        "coverage_pct": round((mesas_reportadas / total_mesas * 100) if total_mesas else 0.0, 2),
        "projection_scale": round(projection_scale, 4),
        "total_votes": total_votes,
        "formulas": formulas_payload,
        "updated_at": datetime.now().isoformat(),
    }


async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT value FROM user_settings WHERE key = ?", (key,))
    return rows[0][0] if rows else default


async def set_setting(key: str, value: str):
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)",
        (key, value))
    await db.commit()


# --- Auth / User management ---

def _normalize_usernames(usernames: list[str] | None) -> list[str]:
    return sorted({username.strip() for username in (usernames or []) if username and username.strip()})


def _user_scope(column: str, usernames: list[str] | None) -> tuple[str, tuple[str, ...]]:
    names = tuple(_normalize_usernames(usernames))
    if not names:
        return "", ()
    placeholders = ", ".join("?" for _ in names)
    return f"WHERE {column} IN ({placeholders})", names


async def list_users() -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT id, username, is_active FROM users ORDER BY id")
    return [dict(row) for row in rows]


async def create_user(username: str, password_hash: str) -> bool:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        await db.commit()
        return True
    except Exception:
        return False


async def get_user(username: str) -> dict | None:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, username, password_hash, is_active FROM users WHERE username = ?",
        (username,),
    )
    return dict(rows[0]) if rows else None


async def deactivate_users(usernames: list[str] | None = None) -> dict:
    db = await get_db()
    user_where, user_params = _user_scope("username", usernames)
    session_where, session_params = _user_scope("username", usernames)
    claim_where, claim_params = _user_scope("claimed_by", usernames)

    users = await db.execute_fetchall(f"SELECT username FROM users {user_where}", user_params)
    sessions = await db.execute_fetchall(f"SELECT token FROM sessions {session_where}", session_params)
    claims = await db.execute_fetchall(f"SELECT claimed_by FROM queue_claims {claim_where}", claim_params)

    if users:
        await db.execute(f"UPDATE users SET is_active = 0 {user_where}", user_params)
    if sessions:
        await db.execute(f"DELETE FROM sessions {session_where}", session_params)
    if claims:
        await db.execute(f"DELETE FROM queue_claims {claim_where}", claim_params)
    await db.commit()

    return {
        "users": len(users),
        "sessions": len(sessions),
        "claims": len(claims),
    }


async def delete_users(usernames: list[str] | None = None) -> dict:
    db = await get_db()
    user_where, user_params = _user_scope("username", usernames)
    session_where, session_params = _user_scope("username", usernames)
    claim_where, claim_params = _user_scope("claimed_by", usernames)

    users = await db.execute_fetchall(f"SELECT username FROM users {user_where}", user_params)
    sessions = await db.execute_fetchall(f"SELECT token FROM sessions {session_where}", session_params)
    claims = await db.execute_fetchall(f"SELECT claimed_by FROM queue_claims {claim_where}", claim_params)

    if sessions:
        await db.execute(f"DELETE FROM sessions {session_where}", session_params)
    if claims:
        await db.execute(f"DELETE FROM queue_claims {claim_where}", claim_params)
    if users:
        await db.execute(f"DELETE FROM users {user_where}", user_params)
    await db.commit()

    return {
        "users": len(users),
        "sessions": len(sessions),
        "claims": len(claims),
    }


async def create_session(token: str, username: str):
    db = await get_db()
    await db.execute(
        "INSERT INTO sessions (token, username, created_at) VALUES (?, ?, ?)",
        (token, username, datetime.now().isoformat()),
    )
    await db.commit()


async def get_session(token: str) -> str | None:
    """Return username for a valid session token, or None."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT username FROM sessions WHERE token = ?", (token,)
    )
    return rows[0]["username"] if rows else None


async def delete_session(token: str):
    db = await get_db()
    await db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    await db.commit()


# --- Manual validations ---

_MANUAL_QUEUE_SOURCE_SQL = """
    SELECT d.municipio_cod, d.zona_cod, d.puesto_cod, d.mesa,
           d.corporacion, r.ph_total_votos, r.ph_votos_lista,
           r.votos_urna, r.ocr_confidence, r.processed_at,
           d.filepath, p.municipio, p.nombre AS puesto_nombre,
           r.status AS result_status,
           CASE
               WHEN r.id IS NULL THEN 1
               WHEN r.status IN ('processed', 'corrected') THEN 0
               ELSE 1
           END AS needs_manual_votes,
           CASE
               WHEN r.id IS NULL THEN d.downloaded_at
               ELSE COALESCE(r.processed_at, d.downloaded_at)
           END AS queue_sort_at
    FROM e14_downloads d
    LEFT JOIN e14_results r
        ON r.municipio_cod = d.municipio_cod
        AND r.zona_cod = d.zona_cod
        AND r.puesto_cod = d.puesto_cod
        AND r.mesa = d.mesa
        AND r.corporacion = d.corporacion
    LEFT JOIN puestos p ON p.municipio_cod = d.municipio_cod
        AND p.zona_cod = d.zona_cod AND p.puesto_cod = d.puesto_cod
    WHERE r.id IS NULL OR r.status IN ('processed', 'corrected', 'error', 'not_digitized')
"""


_UNCLAIMED_QUEUE_SQL = f"""
    WITH queue_candidates AS (
        {_MANUAL_QUEUE_SOURCE_SQL}
    )
    SELECT qcand.municipio_cod, qcand.zona_cod, qcand.puesto_cod, qcand.mesa,
           qcand.corporacion, qcand.ph_total_votos, qcand.ph_votos_lista,
           qcand.votos_urna, qcand.ocr_confidence, qcand.processed_at,
           qcand.filepath, qcand.municipio, qcand.puesto_nombre,
           qcand.result_status, qcand.needs_manual_votes
    FROM queue_candidates qcand
    LEFT JOIN manual_validations mv
        ON mv.municipio_cod = qcand.municipio_cod
        AND mv.zona_cod = qcand.zona_cod
        AND mv.puesto_cod = qcand.puesto_cod
        AND mv.mesa = qcand.mesa
        AND mv.corporacion = qcand.corporacion
    LEFT JOIN queue_claims qclaim
        ON qclaim.municipio_cod = qcand.municipio_cod
        AND qclaim.zona_cod = qcand.zona_cod
        AND qclaim.puesto_cod = qcand.puesto_cod
        AND qclaim.mesa = qcand.mesa
        AND qclaim.corporacion = qcand.corporacion
    WHERE mv.id IS NULL
      AND qclaim.claimed_by IS NULL
    ORDER BY qcand.needs_manual_votes DESC, qcand.queue_sort_at DESC
    LIMIT 2
"""


async def get_next_unvalidated(username: str) -> tuple[dict | None, str | None]:
    """Return (item, prefetch_url) where prefetch_url is the screenshot URL
    of the item after next (for client-side preloading).
    """
    db = await get_db()

    # 1. Return existing claim for this user if any
    claimed = await db.execute_fetchall(
        f"""
        WITH queue_candidates AS (
            {_MANUAL_QUEUE_SOURCE_SQL}
        )
        SELECT qcand.municipio_cod, qcand.zona_cod, qcand.puesto_cod, qcand.mesa,
               qcand.corporacion, qcand.ph_total_votos, qcand.ph_votos_lista,
               qcand.votos_urna, qcand.ocr_confidence, qcand.processed_at,
               qcand.filepath, qcand.municipio, qcand.puesto_nombre,
               qcand.result_status, qcand.needs_manual_votes
        FROM queue_claims qc
        JOIN queue_candidates qcand
            ON qcand.municipio_cod = qc.municipio_cod
            AND qcand.zona_cod = qc.zona_cod
            AND qcand.puesto_cod = qc.puesto_cod
            AND qcand.mesa = qc.mesa
            AND qcand.corporacion = qc.corporacion
        WHERE qc.claimed_by = ?
        LIMIT 1
        """,
        (username,),
    )
    if claimed:
        r = dict(claimed[0])
        mun, zona, puesto, mesa, corp = (
            r["municipio_cod"], r["zona_cod"], r["puesto_cod"], r["mesa"], r["corporacion"]
        )
        r["screenshot_url"] = f"/api/validar/screenshot/{mun}/{zona}/{puesto}/{mesa}/{corp}"
        r["needs_manual_votes"] = bool(r.get("needs_manual_votes"))
        # Peek at next unclaimed item for prefetch
        peek = await db.execute_fetchall(_UNCLAIMED_QUEUE_SQL)
        prefetch_url = None
        if peek:
            p2 = dict(peek[0])
            prefetch_url = (f"/api/validar/screenshot/{p2['municipio_cod']}/{p2['zona_cod']}"
                            f"/{p2['puesto_cod']}/{p2['mesa']}/{p2['corporacion']}")
        return r, prefetch_url

    # 2. Find next two unclaimed, unvalidated items (first is claimed, second is prefetch)
    rows = await db.execute_fetchall(_UNCLAIMED_QUEUE_SQL)
    if not rows:
        return None, None

    r = dict(rows[0])
    mun, zona, puesto, mesa, corp = (
        r["municipio_cod"], r["zona_cod"], r["puesto_cod"], r["mesa"], r["corporacion"]
    )

    # Prefetch URL = second row if available
    prefetch_url = None
    if len(rows) > 1:
        p2 = dict(rows[1])
        prefetch_url = (f"/api/validar/screenshot/{p2['municipio_cod']}/{p2['zona_cod']}"
                        f"/{p2['puesto_cod']}/{p2['mesa']}/{p2['corporacion']}")

    # 3. Claim it for this user
    await db.execute(
        """
        INSERT INTO queue_claims
            (municipio_cod, zona_cod, puesto_cod, mesa, corporacion, claimed_by, claimed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(claimed_by) DO UPDATE SET
            municipio_cod = excluded.municipio_cod,
            zona_cod = excluded.zona_cod,
            puesto_cod = excluded.puesto_cod,
            mesa = excluded.mesa,
            corporacion = excluded.corporacion,
            claimed_at = excluded.claimed_at
        """,
        (mun, zona, puesto, mesa, corp, username, datetime.now().isoformat()),
    )
    await db.commit()

    r["screenshot_url"] = f"/api/validar/screenshot/{mun}/{zona}/{puesto}/{mesa}/{corp}"
    r["needs_manual_votes"] = bool(r.get("needs_manual_votes"))
    return r, prefetch_url


async def release_claim(username: str):
    """Release the queue claim held by this user."""
    db = await get_db()
    await db.execute("DELETE FROM queue_claims WHERE claimed_by = ?", (username,))
    await db.commit()


async def get_pending_queue_items() -> list[dict]:
    """Return all items still pending manual validation (not yet in manual_validations)."""
    db = await get_db()
    rows = await db.execute_fetchall(
        f"""
        WITH queue_candidates AS (
            {_MANUAL_QUEUE_SOURCE_SQL}
        )
        SELECT qcand.municipio_cod, qcand.zona_cod, qcand.puesto_cod, qcand.mesa,
               qcand.corporacion, qcand.ph_total_votos, qcand.needs_manual_votes,
               qcand.municipio, qcand.puesto_nombre, qcand.result_status,
               qcand.ocr_confidence, qcand.votos_urna
        FROM queue_candidates qcand
        LEFT JOIN manual_validations mv
            ON mv.municipio_cod = qcand.municipio_cod
            AND mv.zona_cod = qcand.zona_cod
            AND mv.puesto_cod = qcand.puesto_cod
            AND mv.mesa = qcand.mesa
            AND mv.corporacion = qcand.corporacion
        WHERE mv.id IS NULL
        ORDER BY qcand.needs_manual_votes DESC, qcand.queue_sort_at DESC
        """
    )
    return [dict(r) for r in rows]


async def get_validation_stats() -> dict:
    db = await get_db()
    rows = await db.execute_fetchall(
        f"""
        WITH queue_candidates AS (
            {_MANUAL_QUEUE_SOURCE_SQL}
        ),
        unvalidated_queue AS (
            SELECT qcand.*
            FROM queue_candidates qcand
            LEFT JOIN manual_validations mv
                ON mv.municipio_cod = qcand.municipio_cod
                AND mv.zona_cod = qcand.zona_cod
                AND mv.puesto_cod = qcand.puesto_cod
                AND mv.mesa = qcand.mesa
                AND mv.corporacion = qcand.corporacion
            WHERE mv.id IS NULL
        )
        SELECT
            (SELECT COUNT(*) FROM e14_results
             WHERE status IN ('processed', 'corrected')) AS total_processed,
            (SELECT COUNT(*) FROM queue_candidates) AS total_queue_items,
            (SELECT COUNT(*) FROM manual_validations) AS total_validated,
            (SELECT COUNT(*) FROM unvalidated_queue) AS pending_queue,
            (SELECT COUNT(*) FROM unvalidated_queue WHERE needs_manual_votes = 1) AS pending_without_ocr,
            (SELECT COUNT(*) FROM manual_validations WHERE action = 'corrected') AS total_corrected,
            (SELECT COUNT(*) FROM manual_validations WHERE novelty_note IS NOT NULL) AS total_novelty
        """
    )
    r = rows[0]
    return {
        "total_processed": r[0] or 0,
        "total_queue_items": r[1] or 0,
        "total_validated": r[2] or 0,
        "pending": r[3] or 0,
        "pending_without_ocr": r[4] or 0,
        "total_corrected": r[5] or 0,
        "total_novelty": r[6] or 0,
    }


async def submit_validation(data: dict):
    db = await get_db()
    mun = data["municipio_cod"]
    zona = data["zona_cod"]
    puesto = data["puesto_cod"]
    mesa = data["mesa"]
    corp = data["corporacion"]
    now = datetime.now().isoformat()

    existing_rows = await db.execute_fetchall(
        """
        SELECT id, download_id, status
        FROM e14_results
        WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
          AND mesa = ? AND corporacion = ?
        LIMIT 1
        """,
        (mun, zona, puesto, mesa, corp),
    )
    existing = dict(existing_rows[0]) if existing_rows else None

    if data["action"] == "approved" and (
        not existing or existing["status"] not in ("processed", "corrected")
    ):
        raise ValueError("No hay OCR para aprobar; ingresa el valor manual.")

    await db.execute(
        """
        INSERT INTO manual_validations
            (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
             validated_by, action, corrected_ph_votes, novelty_note, validated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
        DO UPDATE SET
            validated_by = excluded.validated_by,
            action = excluded.action,
            corrected_ph_votes = excluded.corrected_ph_votes,
            novelty_note = excluded.novelty_note,
            validated_at = excluded.validated_at
        """,
        (
            mun, zona, puesto, mesa, corp,
            data["validated_by"],
            data["action"],
            data.get("corrected_ph_votes"),
            data.get("novelty_note"),
            now,
        ),
    )

    # If corrected, update or create the result row so manual capture becomes canonical.
    if data["action"] == "corrected" and data.get("corrected_ph_votes") is not None:
        if existing:
            await db.execute(
                """
                UPDATE e14_results SET
                    ph_total_votos = ?,
                    status = 'corrected',
                    error_message = NULL,
                    corrected_by = ?,
                    corrected_at = ?,
                    processed_at = COALESCE(processed_at, ?)
                WHERE id = ?
                """,
                (
                    data["corrected_ph_votes"],
                    data["validated_by"],
                    now,
                    now,
                    existing["id"],
                ),
            )
        else:
            download_rows = await db.execute_fetchall(
                """
                SELECT id
                FROM e14_downloads
                WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
                  AND mesa = ? AND corporacion = ?
                LIMIT 1
                """,
                (mun, zona, puesto, mesa, corp),
            )
            if not download_rows:
                raise ValueError("No se encontro el PDF descargado para esta mesa.")
            download_id = download_rows[0]["id"]
            await db.execute(
                """
                INSERT INTO e14_results (
                    download_id, municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
                    ph_total_votos, status, processed_at, corrected_by, corrected_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'corrected', ?, ?, ?)
                ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
                DO UPDATE SET
                    download_id = excluded.download_id,
                    ph_total_votos = excluded.ph_total_votos,
                    status = 'corrected',
                    error_message = NULL,
                    processed_at = COALESCE(e14_results.processed_at, excluded.processed_at),
                    corrected_by = excluded.corrected_by,
                    corrected_at = excluded.corrected_at
                """,
                (
                    download_id,
                    mun,
                    zona,
                    puesto,
                    mesa,
                    corp,
                    data["corrected_ph_votes"],
                    now,
                    data["validated_by"],
                    now,
                ),
            )

    # Release the claim so the next item can be assigned
    await db.execute(
        "DELETE FROM queue_claims WHERE claimed_by = ?",
        (data["validated_by"],),
    )

    await db.commit()


async def undo_last_validation(username: str) -> dict | None:
    """Delete the most recent (non-novelty) validation by this user and re-claim it."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """
        SELECT mv.id, mv.municipio_cod, mv.zona_cod, mv.puesto_cod,
               mv.mesa, mv.corporacion,
               r.ph_total_votos, r.ph_votos_lista, r.votos_urna,
               r.ocr_confidence, r.processed_at, d.filepath,
               p.municipio, p.nombre as puesto_nombre
        FROM manual_validations mv
        JOIN e14_results r
            ON r.municipio_cod = mv.municipio_cod
            AND r.zona_cod = mv.zona_cod
            AND r.puesto_cod = mv.puesto_cod
            AND r.mesa = mv.mesa
            AND r.corporacion = mv.corporacion
        JOIN e14_downloads d ON d.id = r.download_id
        LEFT JOIN puestos p ON p.municipio_cod = mv.municipio_cod
            AND p.zona_cod = mv.zona_cod AND p.puesto_cod = mv.puesto_cod
        WHERE mv.validated_by = ?
          AND (mv.novelty_note IS NULL OR mv.novelty_note = '')
        ORDER BY mv.validated_at DESC
        LIMIT 1
        """,
        (username,),
    )
    if not rows:
        return None

    r = dict(rows[0])
    val_id = r.pop("id")
    mun, zona, puesto, mesa, corp = (
        r["municipio_cod"], r["zona_cod"], r["puesto_cod"], r["mesa"], r["corporacion"]
    )

    await db.execute("DELETE FROM manual_validations WHERE id = ?", (val_id,))
    # Release any current claim, then re-claim the undone item
    await db.execute("DELETE FROM queue_claims WHERE claimed_by = ?", (username,))
    await db.execute(
        """
        INSERT OR IGNORE INTO queue_claims
            (municipio_cod, zona_cod, puesto_cod, mesa, corporacion, claimed_by, claimed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (mun, zona, puesto, mesa, corp, username, datetime.now().isoformat()),
    )
    await db.commit()

    r["screenshot_url"] = f"/api/validar/screenshot/{mun}/{zona}/{puesto}/{mesa}/{corp}"
    return r


async def get_novelty_reports() -> list[dict]:
    """Return all manual validations that have a novelty note, with full mesa info."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """
        SELECT
            mv.id, mv.municipio_cod, mv.zona_cod, mv.puesto_cod, mv.mesa,
            mv.corporacion, mv.validated_by, mv.action,
            mv.corrected_ph_votes, mv.novelty_note, mv.validated_at,
            mv.resolved_at, mv.resolved_by,
            r.ph_total_votos as ai_ph_votes,
            r.votos_urna,
            r.ocr_confidence,
            p.municipio,
            p.nombre as puesto_nombre,
            p.departamento
        FROM manual_validations mv
        JOIN e14_results r
            ON r.municipio_cod = mv.municipio_cod
            AND r.zona_cod = mv.zona_cod
            AND r.puesto_cod = mv.puesto_cod
            AND r.mesa = mv.mesa
            AND r.corporacion = mv.corporacion
        LEFT JOIN puestos p
            ON p.municipio_cod = mv.municipio_cod
            AND p.zona_cod = mv.zona_cod
            AND p.puesto_cod = mv.puesto_cod
        WHERE mv.novelty_note IS NOT NULL AND mv.novelty_note != ''
        ORDER BY mv.resolved_at IS NOT NULL, mv.validated_at DESC
        """
    )
    return [dict(r) for r in rows]


async def resolve_novelty(novelty_id: int, resolved_by: str,
                          corrected_ph_votes: int | None = None) -> bool:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM manual_validations WHERE id = ?", (novelty_id,)
    )
    if not rows:
        return False
    mv = rows[0]
    now = datetime.now().isoformat()
    await db.execute(
        """UPDATE manual_validations
           SET resolved_at = ?, resolved_by = ?,
               corrected_ph_votes = COALESCE(?, corrected_ph_votes)
           WHERE id = ?""",
        (now, resolved_by, corrected_ph_votes, novelty_id),
    )
    if corrected_ph_votes is not None:
        await db.execute(
            """UPDATE e14_results SET ph_total_votos = ?, status = 'corrected',
               corrected_by = ?, corrected_at = ?
               WHERE municipio_cod=? AND zona_cod=? AND puesto_cod=? AND mesa=? AND corporacion=?""",
            (corrected_ph_votes, resolved_by, now,
             mv["municipio_cod"], mv["zona_cod"], mv["puesto_cod"], mv["mesa"], mv["corporacion"]),
        )
    await db.commit()
    return True


async def unresolve_novelty(novelty_id: int) -> bool:
    db = await get_db()
    await db.execute(
        "UPDATE manual_validations SET resolved_at = NULL, resolved_by = NULL WHERE id = ?",
        (novelty_id,),
    )
    await db.commit()
    return True


async def get_all_validations(search: str = "") -> list[dict]:
    """Return all manual validations for admin review, with full mesa info."""
    db = await get_db()
    query = """
        SELECT
            mv.id, mv.municipio_cod, mv.zona_cod, mv.puesto_cod, mv.mesa,
            mv.corporacion, mv.validated_by, mv.action,
            mv.corrected_ph_votes, mv.novelty_note, mv.validated_at,
            r.ph_total_votos as ai_ph_votes,
            r.votos_urna, r.ocr_confidence,
            p.municipio, p.nombre as puesto_nombre, p.departamento
        FROM manual_validations mv
        JOIN e14_results r
            ON r.municipio_cod = mv.municipio_cod AND r.zona_cod = mv.zona_cod
            AND r.puesto_cod = mv.puesto_cod AND r.mesa = mv.mesa
            AND r.corporacion = mv.corporacion
        LEFT JOIN puestos p
            ON p.municipio_cod = mv.municipio_cod AND p.zona_cod = mv.zona_cod
            AND p.puesto_cod = mv.puesto_cod
    """
    params: list = []
    if search:
        query += """
        WHERE mv.id = CAST(? AS INTEGER)
           OR mv.validated_by LIKE ?
           OR p.municipio LIKE ?
           OR p.nombre LIKE ?
        """
        like = f"%{search}%"
        params = [search, like, like, like]
    query += " ORDER BY mv.validated_at DESC LIMIT 200"
    rows = await db.execute_fetchall(query, params)
    return [dict(r) for r in rows]


async def admin_correct_validation(validation_id: int, new_votes: int, admin_user: str):
    """Overwrite a manual validation's corrected_ph_votes and update e14_results."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM manual_validations WHERE id = ?", (validation_id,)
    )
    if not rows:
        return False
    mv = rows[0]
    now = datetime.now().isoformat()
    await db.execute(
        """UPDATE manual_validations SET
               action = 'corrected',
               corrected_ph_votes = ?,
               validated_by = ?,
               validated_at = ?
           WHERE id = ?""",
        (new_votes, admin_user, now, validation_id),
    )
    await db.execute(
        """UPDATE e14_results SET
               ph_total_votos = ?,
               status = 'corrected',
               corrected_by = ?,
               corrected_at = ?
           WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
             AND mesa = ? AND corporacion = ?""",
        (new_votes, admin_user, now,
         mv["municipio_cod"], mv["zona_cod"], mv["puesto_cod"],
         mv["mesa"], mv["corporacion"]),
    )
    await db.commit()
    return True


async def add_novelty_note(mun: str, zona: str, puesto: str, mesa: int,
                            corp: str, username: str, note: str):
    """Add/update novelty note on an existing validation, or create one if absent."""
    db = await get_db()
    await db.execute(
        """
        INSERT INTO manual_validations
            (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
             validated_by, action, novelty_note, validated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'novelty', ?, ?)
        ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
        DO UPDATE SET
            novelty_note = excluded.novelty_note,
            validated_at = excluded.validated_at
        """,
        (mun, zona, puesto, mesa, corp, username, note, datetime.now().isoformat()),
    )
    await db.commit()

    # Create/update a blue alert so novelties appear on map and hierarchy table
    await upsert_alert({
        "municipio_cod": mun,
        "zona_cod": zona,
        "puesto_cod": puesto,
        "mesa": mesa,
        "alert_type": f"novelty_{corp}",
        "severity": "info",
        "description": f"Novedad ({corp}) reportada por {username}: {note[:200]}",
        "created_at": datetime.now().isoformat(),
    })


async def save_crop_override(mun: str, zona: str, puesto: str, mesa: int,
                              corp: str, username: str,
                              x0: float, y0: float, x1: float, y1: float):
    """Save a manual crop override for a specific mesa/corp PDF."""
    db = await get_db()
    await db.execute(
        """
        INSERT INTO crop_overrides
            (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
             x0_pct, y0_pct, x1_pct, y1_pct, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
        DO UPDATE SET
            x0_pct = excluded.x0_pct, y0_pct = excluded.y0_pct,
            x1_pct = excluded.x1_pct, y1_pct = excluded.y1_pct,
            created_by = excluded.created_by, created_at = excluded.created_at
        """,
        (mun, zona, puesto, mesa, corp, x0, y0, x1, y1, username, datetime.now().isoformat()),
    )
    await db.commit()


async def get_e14_progress() -> dict:
    """Full progress stats: downloaded, processed, validated, by corp, by validator."""
    db = await get_db()
    rows = await db.execute_fetchall("""
        SELECT
            (SELECT SUM(mesas) * 2 FROM puestos)                               AS total_mesas,
            (SELECT COUNT(*) FROM e14_downloads)                                AS downloaded,
            (SELECT COUNT(*) FROM e14_results WHERE status IN ('processed','corrected'))
                                                                                AS processed,
            (SELECT COUNT(*) FROM e14_results WHERE status = 'error')          AS errors,
            (SELECT COUNT(*) FROM manual_validations)                           AS validated,
            (SELECT COUNT(*) FROM manual_validations WHERE action='corrected')  AS corrected,
            (SELECT COUNT(*) FROM manual_validations WHERE action='novelty'
                OR (novelty_note IS NOT NULL AND novelty_note != ''))           AS novelty
    """)
    r = rows[0]
    total_mesas   = r[0] or 0
    downloaded    = r[1] or 0
    processed     = r[2] or 0
    errors        = r[3] or 0
    validated     = r[4] or 0
    corrected     = r[5] or 0
    novelty       = r[6] or 0

    # By corporacion
    corp_rows = await db.execute_fetchall("""
        SELECT
            d.corporacion,
            COUNT(DISTINCT d.id)   AS downloaded,
            COUNT(DISTINCT CASE WHEN r.status IN ('processed','corrected') THEN r.id END) AS processed,
            COUNT(DISTINCT mv.id)  AS validated
        FROM e14_downloads d
        LEFT JOIN e14_results r
            ON r.municipio_cod=d.municipio_cod AND r.zona_cod=d.zona_cod
            AND r.puesto_cod=d.puesto_cod AND r.mesa=d.mesa AND r.corporacion=d.corporacion
        LEFT JOIN manual_validations mv
            ON mv.municipio_cod=d.municipio_cod AND mv.zona_cod=d.zona_cod
            AND mv.puesto_cod=d.puesto_cod AND mv.mesa=d.mesa AND mv.corporacion=d.corporacion
        GROUP BY d.corporacion
        ORDER BY d.corporacion
    """)
    by_corp = {}
    for cr in corp_rows:
        dl = cr["downloaded"] or 0
        pr = cr["processed"] or 0
        vl = cr["validated"] or 0
        by_corp[cr["corporacion"]] = {
            "downloaded": dl,
            "processed":  pr,
            "validated":  vl,
            "pending":    max(0, pr - vl),
        }

    # By validator
    val_rows = await db.execute_fetchall("""
        SELECT
            validated_by,
            COUNT(*) AS total,
            SUM(CASE WHEN action='approved' THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN action='corrected' THEN 1 ELSE 0 END) AS corrected,
            SUM(CASE WHEN action='novelty'
                OR (novelty_note IS NOT NULL AND novelty_note != '') THEN 1 ELSE 0 END) AS novelty,
            MAX(validated_at) AS last_at
        FROM manual_validations
        GROUP BY validated_by
        ORDER BY total DESC
    """)
    by_validator = [dict(vr) for vr in val_rows]

    return {
        "total_mesas":  total_mesas,
        "downloaded":   downloaded,
        "processed":    processed,
        "errors":       errors,
        "validated":    validated,
        "pending":      max(0, processed - validated),
        "corrected":    corrected,
        "novelty":      novelty,
        "pct_downloaded": round(downloaded / total_mesas * 100, 1) if total_mesas else 0,
        "pct_processed":  round(processed  / downloaded  * 100, 1) if downloaded  else 0,
        "pct_validated":  round(validated  / processed   * 100, 1) if processed   else 0,
        "by_corp":      by_corp,
        "by_validator": by_validator,
    }


async def get_crop_override(mun: str, zona: str, puesto: str, mesa: int,
                             corp: str) -> tuple[float, float, float, float] | None:
    """Return (x0, y0, x1, y1) fractions if a manual crop override exists, else None."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT x0_pct, y0_pct, x1_pct, y1_pct FROM crop_overrides
           WHERE municipio_cod=? AND zona_cod=? AND puesto_cod=?
             AND mesa=? AND corporacion=? LIMIT 1""",
        (mun, zona, puesto, mesa, corp),
    )
    if rows:
        r = rows[0]
        return (r["x0_pct"], r["y0_pct"], r["x1_pct"], r["y1_pct"])
    return None


# ── Field-level validations (Tinder por candidato) ───────────────────────────

async def seed_field_validations(
    municipio_cod: str, zona_cod: str, puesto_cod: str, mesa: int,
    corporacion: str, sections_json: str, ocr_results: dict
) -> int:
    """Crea filas pending en field_validations para cada campo del acta.

    Campos sembrados (en orden de prioridad para el Tinder):
      1. Candidatos prioritarios: Cepeda(1), Espriella(4), Valencia(11)
      2. Votos especiales: blancos, nulos, no marcados, suma total
      3. Nivelación: E-11, urna
      4. Firmas jurados 1-6
      5. Recuento de votos
      6. Resto de candidatos

    Solo inserta si no existe ya (IGNORE).
    """
    db = await get_db()
    try:
        sections = json.loads(sections_json or "[]")
    except Exception:
        sections = []

    inserted = 0
    now = datetime.now().isoformat()

    # Prioridad numérica para el ORDER BY del Tinder
    # Menor número = aparece primero
    PRIORITY: dict[str, int] = {
        # Candidatos prioritarios
        "cand_1":  10,   # Iván Cepeda Castro
        "cand_4":  11,   # Abelardo de la Espriella
        "cand_11": 12,   # Paloma Valencia Laserna
        # Votos especiales
        "blancos":      20,
        "nulos":        21,
        "no_marcados":  22,
        "suma_total":   23,
        # Nivelación
        "niv_e11":  30,
        "niv_urna": 31,
        # Firmas
        "firma_1": 40,
        "firma_2": 41,
        "firma_3": 42,
        "firma_4": 43,
        "firma_5": 44,
        "firma_6": 45,
        # Recuento
        "recuento": 50,
        # Resto de candidatos (se asigna 60 + numero)
    }

    async def _insert(region_id: str, tipo: str, label: str,
                      ocr_val, ocr_raw: str = "", ocr_conf=None):
        nonlocal inserted
        priority = PRIORITY.get(region_id, 60 + int(''.join(filter(str.isdigit, region_id)) or '99'))
        await db.execute(
            """INSERT OR IGNORE INTO field_validations
               (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
                region_id, tipo, campo_label, ocr_valor, ocr_raw, ocr_conf,
                sort_priority, action, validated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)""",
            (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
             region_id, tipo, label, ocr_val, ocr_raw, ocr_conf,
             priority, now),
        )
        inserted += 1

    # ── Candidatos ────────────────────────────────────────────────────────
    for s in sections:
        tipo = s.get("tipo", "otro")
        if tipo != "formula":
            continue
        codigo   = s.get("codigo", "")
        nombre   = s.get("candidato_presidente") or s.get("nombre", "")
        partido  = s.get("partido", "")
        ocr_val  = int(s.get("total_votos", 0) or 0)
        rid      = f"cand_{codigo}"
        label    = f"Candidato {codigo} - {nombre[:40]}"
        if partido:
            label += f" ({partido[:28]})"
        await _insert(rid, "candidato", label, ocr_val, str(ocr_val))

    # ── Votos especiales ──────────────────────────────────────────────────
    for s in sections:
        tipo = s.get("tipo", "otro")
        ocr_val = int(s.get("total_votos", 0) or 0)
        if tipo == "votos_en_blanco":
            await _insert("blancos",     "blancos_nulos", "Votos en Blanco",     ocr_val, str(ocr_val))
        elif tipo == "votos_nulos":
            await _insert("nulos",       "blancos_nulos", "Votos Nulos",         ocr_val, str(ocr_val))
        elif tipo == "votos_no_marcados":
            await _insert("no_marcados", "blancos_nulos", "Votos No Marcados",   ocr_val, str(ocr_val))

    # Suma total (calculada)
    suma = sum(int(s.get("total_votos", 0) or 0) for s in sections if s.get("tipo") == "formula")
    suma += sum(int(s.get("total_votos", 0) or 0) for s in sections
                if s.get("tipo") in ("votos_en_blanco","votos_nulos","votos_no_marcados"))
    await _insert("suma_total", "blancos_nulos", "Suma Total (candidatos+especiales)", suma, str(suma))

    # ── Nivelación ────────────────────────────────────────────────────────
    await _insert("niv_e11",  "nivelacion", "Total Votantes E-11",
                  ocr_results.get("votantes_e11"), str(ocr_results.get("votantes_e11") or ""))
    await _insert("niv_urna", "nivelacion", "Total Votos en Urna",
                  ocr_results.get("votos_urna"),   str(ocr_results.get("votos_urna") or ""))

    # ── Firmas de jurados (1-6) ───────────────────────────────────────────
    firmas_list = ocr_results.get("firmas", [])
    for i in range(1, 7):
        presente = bool(firmas_list[i-1]) if i <= len(firmas_list) else None
        ocr_val_firma = 1 if presente else 0
        raw_firma = "PRESENTE" if presente else ("AUSENTE" if presente is not None else "")
        await _insert(f"firma_{i}", "firmas",
                      f"Firma Jurado {i}", ocr_val_firma, raw_firma)

    # ── Recuento ──────────────────────────────────────────────────────────
    recuento = ocr_results.get("tiene_recuento")
    recuento_val = 1 if recuento else (0 if recuento is False else None)
    recuento_raw = "SI" if recuento else ("NO" if recuento is False else "")
    await _insert("recuento", "recuento", "Hubo recuento de votos", recuento_val, recuento_raw)

    await db.commit()
    return inserted


async def get_next_field_to_validate(username: str) -> dict | None:
    """Devuelve el siguiente campo pendiente de validación para el Tinder.

    Orden: mesas más antiguas primero, campo con menor region_id primero.
    Incluye los datos del PDF necesarios para mostrar el pantallazo.
    """
    db = await get_db()

    # Buscar el próximo campo no validado ni reclamado
    rows = await db.execute_fetchall("""
        SELECT fv.*,
               d.filepath,
               p.municipio,
               p.nombre AS puesto_nombre,
               r.ocr_confidence
        FROM field_validations fv
        JOIN e14_downloads d
            ON d.municipio_cod = fv.municipio_cod
            AND d.zona_cod     = fv.zona_cod
            AND d.puesto_cod   = fv.puesto_cod
            AND d.mesa         = fv.mesa
            AND d.corporacion  = fv.corporacion
        LEFT JOIN puestos p
            ON p.municipio_cod = fv.municipio_cod
            AND p.zona_cod     = fv.zona_cod
            AND p.puesto_cod   = fv.puesto_cod
        LEFT JOIN e14_results r
            ON r.municipio_cod = fv.municipio_cod
            AND r.zona_cod     = fv.zona_cod
            AND r.puesto_cod   = fv.puesto_cod
            AND r.mesa         = fv.mesa
            AND r.corporacion  = fv.corporacion
        WHERE (fv.action IS NULL OR fv.action = 'pending')
        ORDER BY
            fv.sort_priority ASC,       -- 1=Cepeda, 4=Espriella, 11=Valencia, 20-23=especiales...
            fv.municipio_cod ASC,
            fv.mesa ASC
        LIMIT 1
    """)

    if not rows:
        return None

    row = dict(rows[0])
    return row


async def submit_field_validation(
    municipio_cod: str, zona_cod: str, puesto_cod: str,
    mesa: int, corporacion: str, region_id: str,
    action: str, validated_valor: int | None,
    novelty_note: str | None, validated_by: str
) -> bool:
    """Guarda la decisión del validador para un campo individual."""
    db = await get_db()
    now = datetime.now().isoformat()

    await db.execute(
        """UPDATE field_validations
           SET action = ?,
               validated_valor = ?,
               novelty_note = ?,
               validated_by = ?,
               validated_at = ?
           WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
             AND mesa = ? AND corporacion = ? AND region_id = ?""",
        (action,
         validated_valor,
         novelty_note,
         validated_by, now,
         municipio_cod, zona_cod, puesto_cod,
         mesa, corporacion, region_id),
    )
    await db.commit()

    # Si todos los campos de esta mesa están validados → marcar result como corrected
    pending = await db.execute_fetchall(
        """SELECT COUNT(*) AS n FROM field_validations
           WHERE municipio_cod=? AND zona_cod=? AND puesto_cod=?
             AND mesa=? AND corporacion=?
             AND (action IS NULL OR action='pending')""",
        (municipio_cod, zona_cod, puesto_cod, mesa, corporacion),
    )
    if int((pending[0]["n"] if pending else 1) or 1) == 0:
        await db.execute(
            """UPDATE e14_results SET status='corrected', corrected_by=?, corrected_at=?
               WHERE municipio_cod=? AND zona_cod=? AND puesto_cod=? AND mesa=? AND corporacion=?""",
            (validated_by, now,
             municipio_cod, zona_cod, puesto_cod, mesa, corporacion),
        )
        await db.commit()

    return True


async def get_field_validation_stats() -> dict:
    """Estadísticas del Tinder de validación por campo, desglosadas por tipo."""
    db = await get_db()
    rows = await db.execute_fetchall("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN action IS NULL OR action='pending' THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN action='approved'  THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN action='corrected' THEN 1 ELSE 0 END) AS corrected,
            SUM(CASE WHEN action='novelty'   THEN 1 ELSE 0 END) AS novelty,
            SUM(CASE WHEN tipo='candidato'    AND (action IS NULL OR action='pending') THEN 1 ELSE 0 END) AS pending_candidatos,
            SUM(CASE WHEN tipo='blancos_nulos' AND (action IS NULL OR action='pending') THEN 1 ELSE 0 END) AS pending_especiales,
            SUM(CASE WHEN tipo='firmas'        AND (action IS NULL OR action='pending') THEN 1 ELSE 0 END) AS pending_firmas,
            SUM(CASE WHEN tipo='recuento'      AND (action IS NULL OR action='pending') THEN 1 ELSE 0 END) AS pending_recuento,
            SUM(CASE WHEN tipo='nivelacion'    AND (action IS NULL OR action='pending') THEN 1 ELSE 0 END) AS pending_nivelacion
        FROM field_validations
    """)
    r = dict(rows[0]) if rows else {}
    return {
        "total":               int(r.get("total",               0) or 0),
        "pending":             int(r.get("pending",             0) or 0),
        "approved":            int(r.get("approved",            0) or 0),
        "corrected":           int(r.get("corrected",           0) or 0),
        "novelty":             int(r.get("novelty",             0) or 0),
        "pending_candidatos":  int(r.get("pending_candidatos",  0) or 0),
        "pending_especiales":  int(r.get("pending_especiales",  0) or 0),
        "pending_firmas":      int(r.get("pending_firmas",      0) or 0),
        "pending_recuento":    int(r.get("pending_recuento",    0) or 0),
        "pending_nivelacion":  int(r.get("pending_nivelacion",  0) or 0),
    }


async def get_coverage_report(municipio_cod: str | None = None) -> list[dict]:
    """Cobertura DIVIPOL: mesas esperadas vs descargadas vs procesadas vs validadas.

    Agrupa por municipio.  municipio_cod=None devuelve todos los municipios.
    """
    db = await get_db()

    mun_filter = ""
    params: list[object] = []
    if municipio_cod:
        mun_filter = "WHERE p.municipio_cod = ?"
        params.append(municipio_cod)

    rows = await db.execute_fetchall(f"""
        SELECT
            p.municipio_cod,
            MAX(p.municipio)                AS municipio,
            COALESCE(SUM(p.mesas), 0)       AS mesas_divipol,
            COUNT(DISTINCT d.mesa || '-' || d.municipio_cod || '-' || d.zona_cod || '-' || d.puesto_cod)
                                            AS mesas_descargadas,
            COUNT(DISTINCT CASE WHEN r.status IN ('processed','corrected')
                THEN r.mesa || '-' || r.municipio_cod || '-' || r.zona_cod || '-' || r.puesto_cod
                END)                        AS mesas_procesadas,
            (SELECT COUNT(DISTINCT fv.mesa || '-' || fv.municipio_cod || '-' || fv.zona_cod || '-' || fv.puesto_cod)
             FROM field_validations fv
             WHERE fv.municipio_cod = p.municipio_cod
               AND (fv.action IN ('approved','corrected','novelty'))
            )                               AS mesas_con_validacion,
            COUNT(DISTINCT CASE WHEN al.is_resolved = 0 AND al.severity='danger'
                THEN al.id END)             AS alertas_activas
        FROM puestos p
        LEFT JOIN e14_downloads d
            ON d.municipio_cod = p.municipio_cod
            AND d.zona_cod     = p.zona_cod
            AND d.puesto_cod   = p.puesto_cod
            AND d.corporacion  = 'PRES'
        LEFT JOIN e14_results r
            ON r.municipio_cod = p.municipio_cod
            AND r.zona_cod     = p.zona_cod
            AND r.puesto_cod   = p.puesto_cod
            AND r.corporacion  = 'PRES'
        LEFT JOIN alerts al
            ON al.municipio_cod = p.municipio_cod
        {mun_filter}
        GROUP BY p.municipio_cod
        ORDER BY p.municipio_cod
    """, params)

    result = []
    for r in rows:
        divipol  = int(r["mesas_divipol"]        or 0)
        descarg  = int(r["mesas_descargadas"]     or 0)
        proc     = int(r["mesas_procesadas"]      or 0)
        valid    = int(r["mesas_con_validacion"]  or 0)
        alertas  = int(r["alertas_activas"]       or 0)
        result.append({
            "municipio_cod":        r["municipio_cod"],
            "municipio":            r["municipio"],
            "mesas_divipol":        divipol,
            "mesas_descargadas":    descarg,
            "mesas_procesadas":     proc,
            "mesas_validadas":      valid,
            "alertas_activas":      alertas,
            "pct_descargado":  round(descarg / divipol * 100, 1) if divipol else 0,
            "pct_procesado":   round(proc    / divipol * 100, 1) if divipol else 0,
            "pct_validado":    round(valid   / divipol * 100, 1) if divipol else 0,
        })
    return result
