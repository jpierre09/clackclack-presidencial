"""SQLite database management for ClackClack."""
import aiosqlite
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime

from backend.config import CAMARA_CURULES_ANTIOQUIA, CAMARA_TIMELINE_POINTS, DB_PATH

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(str(DB_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


async def init_db():
    db = await get_db()
    await db.executescript(SCHEMA)
    await db.commit()


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
"""


# --- CRUD Operations ---
_PARTY_WORD_RE = re.compile(r"[^A-Z0-9 ]+")
_SPACE_RE = re.compile(r"\s+")
_INDIGENOUS_TOKENS = (
    "INDIGENA",
    "INDIGENAS",
    "AICO",
    "MAIS",
    "CABILDO",
    "RESGUARDO",
)
_PREFERRED_PARTIES = [
    "PARTIDO CONSERVADOR",
    "CREEMOS",
    "PARTIDO LIBERAL",
    "PARTIDO VERDE",
    "PACTO HISTORICO",
    "CENTRO DEMOCRATICO",
    "FUERZA CIUDADANA",
    "CAMBIO RADICAL",
    "PARTIDO DE LA U",
]
_PARTY_LOGOS = {
    "PARTIDO CONSERVADOR": "/party-logos/conservador.png",
    "CREEMOS": "/party-logos/creemos.svg",
    "PARTIDO LIBERAL": "/party-logos/liberal.png",
    "PARTIDO VERDE": "/party-logos/verde.png",
    "PACTO HISTORICO": "/party-logos/pacto-historico.png",
    "CENTRO DEMOCRATICO": "/party-logos/centro-democratico.png",
    "FUERZA CIUDADANA": "/party-logos/fuerza-ciudadana.png",
    "CAMBIO RADICAL": "/party-logos/cambio-radical.png",
    "PARTIDO DE LA U": "/party-logos/partido-u.png",
}


def _normalize_party_name(raw_name: str) -> str:
    text = (raw_name or "").strip().upper()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFD", text)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = _PARTY_WORD_RE.sub(" ", normalized)
    normalized = _SPACE_RE.sub(" ", normalized).strip()
    if "PACT" in normalized and "HISTOR" in normalized:
        return "PACTO HISTORICO"
    return normalized


def _contains_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _map_party_for_dashboard(normalized_name: str) -> str | None:
    if not normalized_name:
        return None
    if _contains_any_token(normalized_name, _INDIGENOUS_TOKENS):
        return None

    if "PACTO HISTORICO" in normalized_name:
        return "PACTO HISTORICO"
    if "CONSERVADOR" in normalized_name:
        return "PARTIDO CONSERVADOR"
    if "CREEMOS" in normalized_name:
        return "CREEMOS"
    if "LIBERAL" in normalized_name:
        return "PARTIDO LIBERAL"
    if "ALIANZA VERDE" in normalized_name or (
        "VERDE" in normalized_name and "PACTO HISTORICO" not in normalized_name
    ):
        return "PARTIDO VERDE"
    if "CENTRO DEMOCRATICO" in normalized_name:
        return "CENTRO DEMOCRATICO"
    if "FUERZA CIUDADANA" in normalized_name:
        return "FUERZA CIUDADANA"
    if "CAMBIO RADICAL" in normalized_name:
        return "CAMBIO RADICAL"
    if "PARTIDO DE LA U" in normalized_name or normalized_name == "LA U":
        return "PARTIDO DE LA U"
    return normalized_name


def _ordered_parties(votes_by_party: dict[str, int]) -> list[str]:
    preferred = [party for party in _PREFERRED_PARTIES if votes_by_party.get(party, 0) > 0]
    extras = sorted(
        [party for party in votes_by_party if party not in _PREFERRED_PARTIES and votes_by_party[party] > 0],
        key=lambda party: (-votes_by_party[party], party),
    )
    return preferred + extras


def _build_visual_seat_order(
    seat_counts: dict[str, int], votes_by_party: dict[str, int], curules_total: int
) -> list[str]:
    order = _ordered_parties(votes_by_party)
    seats: list[str] = []
    for party in order:
        seats.extend([party] * max(0, int(seat_counts.get(party, 0))))
    if len(seats) < curules_total:
        seats.extend([""] * (curules_total - len(seats)))
    return seats[:curules_total]


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


def _extract_party_votes(all_sections_json: str | None) -> dict[str, int]:
    if not all_sections_json:
        return {}
    try:
        sections = json.loads(all_sections_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(sections, list):
        return {}

    votes_by_party: defaultdict[str, int] = defaultdict(int)
    for section in sections:
        if not isinstance(section, dict):
            continue
        if section.get("tipo") != "partido":
            continue
        party_name = _normalize_party_name(str(section.get("nombre") or ""))
        if not party_name:
            continue
        votes = _to_int(section.get("total_votos"))
        if votes <= 0:
            votes = _to_int(section.get("votos_lista"))
        if votes < 0:
            votes = 0
        votes_by_party[party_name] += votes
    return dict(votes_by_party)


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

    party_votes = _extract_party_votes(data.get("all_sections_json"))
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
         status, error_message, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            processed_at = excluded.processed_at""",
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
        ),
    )

    await _refresh_party_votes(db, data)

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
         discrepancy_pct, is_resolved, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, alert_type)
        DO UPDATE SET
            severity = excluded.severity,
            description = excluded.description,
            sen_ph_votes = excluded.sen_ph_votes,
            cam_ph_votes = excluded.cam_ph_votes,
            discrepancy_pct = excluded.discrepancy_pct,
            is_resolved = 0,
            resolved_by = NULL,
            resolved_at = NULL,
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


async def get_hierarchy() -> list[dict]:
    """Get hierarchical data: municipio > zona > puesto with alert counts."""
    db = await get_db()

    # Get all municipios with their alert counts
    rows = await db.execute_fetchall("""
        SELECT
            p.municipio_cod,
            p.municipio,
            SUM(p.mesas) as total_mesas,
            COUNT(DISTINCT a_d.id) as alerts_danger,
            COUNT(DISTINCT a_w.id) as alerts_warning
        FROM puestos p
        LEFT JOIN alerts a_d ON a_d.municipio_cod = p.municipio_cod
            AND a_d.is_resolved = 0 AND a_d.severity = 'danger'
        LEFT JOIN alerts a_w ON a_w.municipio_cod = p.municipio_cod
            AND a_w.is_resolved = 0 AND a_w.severity = 'warning'
        WHERE p.departamento = 'ANTIOQUIA'
        GROUP BY p.municipio_cod, p.municipio
    """)

    municipios = []
    for r in rows:
        mun = dict(r)
        # Get zonas for this municipio
        zonas_rows = await db.execute_fetchall("""
            SELECT
                p.zona_cod,
                SUM(p.mesas) as total_mesas,
                COUNT(DISTINCT a.id) as alert_count
            FROM puestos p
            LEFT JOIN alerts a ON a.municipio_cod = p.municipio_cod
                AND a.zona_cod = p.zona_cod AND a.is_resolved = 0
            WHERE p.municipio_cod = ?
            GROUP BY p.zona_cod
            ORDER BY p.zona_cod
        """, (mun["municipio_cod"],))

        zonas = []
        for z in zonas_rows:
            zona = dict(z)
            # Get puestos for this zona
            puestos_rows = await db.execute_fetchall("""
                SELECT
                    p.puesto_cod, p.nombre, p.mesas, p.lat, p.lon,
                    COUNT(DISTINCT a.id) as alert_count
                FROM puestos p
                LEFT JOIN alerts a ON a.municipio_cod = p.municipio_cod
                    AND a.zona_cod = p.zona_cod AND a.puesto_cod = p.puesto_cod
                    AND a.is_resolved = 0
                WHERE p.municipio_cod = ? AND p.zona_cod = ?
                GROUP BY p.puesto_cod
                ORDER BY p.puesto_cod
            """, (mun["municipio_cod"], zona["zona_cod"]))

            puestos = []
            for pu in puestos_rows:
                puesto = dict(pu)
                # Get mesas for this puesto
                mesas_rows = await db.execute_fetchall("""
                    SELECT
                        m.mesa,
                        rs.ph_total_votos as sen_votes,
                        rc.ph_total_votos as cam_votes,
                        rs.status as sen_status,
                        rc.status as cam_status,
                        rs.ocr_confidence as sen_conf,
                        rc.ocr_confidence as cam_conf,
                        a.alert_type, a.severity, a.discrepancy_pct,
                        CASE WHEN EXISTS (
                            SELECT 1 FROM manual_validations mv2
                            WHERE mv2.municipio_cod = ? AND mv2.zona_cod = ?
                              AND mv2.puesto_cod = ? AND mv2.mesa = m.mesa
                              AND mv2.novelty_note IS NOT NULL AND mv2.novelty_note != ''
                        ) THEN 1 ELSE 0 END as has_novelty
                    FROM (
                        SELECT DISTINCT mesa FROM e14_downloads
                        WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
                    ) m
                    LEFT JOIN e14_results rs ON rs.municipio_cod = ?
                        AND rs.zona_cod = ? AND rs.puesto_cod = ?
                        AND rs.mesa = m.mesa AND rs.corporacion = 'SEN'
                    LEFT JOIN e14_results rc ON rc.municipio_cod = ?
                        AND rc.zona_cod = ? AND rc.puesto_cod = ?
                        AND rc.mesa = m.mesa AND rc.corporacion = 'CAM'
                    LEFT JOIN alerts a ON a.municipio_cod = ?
                        AND a.zona_cod = ? AND a.puesto_cod = ?
                        AND a.mesa = m.mesa AND a.is_resolved = 0
                        AND a.severity != 'info'
                    ORDER BY m.mesa
                """, (mun["municipio_cod"], zona["zona_cod"], puesto["puesto_cod"],
                      mun["municipio_cod"], zona["zona_cod"], puesto["puesto_cod"],
                      mun["municipio_cod"], zona["zona_cod"], puesto["puesto_cod"],
                      mun["municipio_cod"], zona["zona_cod"], puesto["puesto_cod"],
                      mun["municipio_cod"], zona["zona_cod"], puesto["puesto_cod"]))

                puesto["mesas_data"] = [dict(mr) for mr in mesas_rows]
                puestos.append(puesto)

            zona["puestos"] = puestos
            zonas.append(zona)

        mun["zonas"] = zonas
        municipios.append(mun)

    municipios.sort(
        key=lambda item: (
            -int(item.get("alerts_danger", 0) or 0) - int(item.get("alerts_warning", 0) or 0),
            -int(item.get("alerts_danger", 0) or 0),
            str(item.get("municipio", "")),
        )
    )

    return municipios


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
            rs.ph_total_votos as sen_votes_actual,
            rc.ph_total_votos as cam_votes_actual
        FROM alerts a
        JOIN puestos p ON p.municipio_cod = a.municipio_cod
            AND p.zona_cod = a.zona_cod AND p.puesto_cod = a.puesto_cod
        LEFT JOIN e14_results rs ON rs.municipio_cod = a.municipio_cod
            AND rs.zona_cod = a.zona_cod AND rs.puesto_cod = a.puesto_cod
            AND rs.mesa = a.mesa AND rs.corporacion = 'SEN'
        LEFT JOIN e14_results rc ON rc.municipio_cod = a.municipio_cod
            AND rc.zona_cod = a.zona_cod AND rc.puesto_cod = a.puesto_cod
            AND rc.mesa = a.mesa AND rc.corporacion = 'CAM'
        WHERE a.is_resolved = 0 AND a.alert_type = 'vote_discrepancy'
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


def _compute_curules(votes_by_party: dict[str, int], curules_total: int) -> dict:
    cleaned_votes = {
        party: int(votes)
        for party, votes in votes_by_party.items()
        if int(votes) > 0
    }
    total_votes = sum(cleaned_votes.values())

    if curules_total <= 0 or not cleaned_votes:
        return {
            "total_votes": total_votes,
            "cociente_electoral": 0.0,
            "threshold_votes": 0.0,
            "seat_counts": {party: 0 for party in cleaned_votes},
            "seat_order": [],
            "eligible_parties": [],
        }

    cociente = total_votes / curules_total
    threshold_votes = cociente * 0.5
    eligible_votes = {
        party: votes
        for party, votes in cleaned_votes.items()
        if votes >= threshold_votes
    }

    if not eligible_votes:
        eligible_votes = dict(cleaned_votes)
        threshold_votes = 0.0

    quotients: list[tuple[float, int, str, int]] = []
    for party, votes in eligible_votes.items():
        for divisor in range(1, curules_total + 1):
            quotients.append((votes / divisor, votes, party, divisor))
    quotients.sort(key=lambda item: (-item[0], -item[1], item[2]))

    seat_counts = {party: 0 for party in cleaned_votes}
    seat_order: list[str] = []
    for quotient in quotients[:curules_total]:
        party = quotient[2]
        seat_counts[party] = seat_counts.get(party, 0) + 1
        seat_order.append(party)

    return {
        "total_votes": total_votes,
        "cociente_electoral": cociente,
        "threshold_votes": threshold_votes,
        "seat_counts": seat_counts,
        "seat_order": seat_order,
        "eligible_parties": sorted(eligible_votes.keys()),
    }


def _build_party_palette(parties_ordered: list[str]) -> dict[str, str]:
    fixed = {
        "PARTIDO CONSERVADOR": "#1e3288",
        "CREEMOS": "#23a0dc",
        "PARTIDO LIBERAL": "#d22c2c",
        "PARTIDO VERDE": "#00a843",
        "PACTO HISTORICO": "#ff1820",
        "CENTRO DEMOCRATICO": "#2146b7",
        "FUERZA CIUDADANA": "#ff7b2b",
        "CAMBIO RADICAL": "#c01245",
        "PARTIDO DE LA U": "#f3a300",
    }
    base_colors = [
        "#4e79a7",
        "#f28e2b",
        "#e15759",
        "#76b7b2",
        "#13b0b7",
        "#ce6f00",
        "#5f6a72",
        "#7f8f3e",
        "#9f5f80",
        "#2d7e6b",
        "#8b3f2d",
        "#5e4da1",
    ]
    palette: dict[str, str] = {}
    for idx, party in enumerate(parties_ordered):
        if party in fixed:
            palette[party] = fixed[party]
        else:
            palette[party] = base_colors[idx % len(base_colors)]
    return palette


async def get_camara_live_projection() -> dict:
    db = await get_db()

    mesas_row = await db.execute_fetchall(
        """SELECT COALESCE(SUM(mesas), 0) AS total_mesas
           FROM puestos WHERE departamento = 'ANTIOQUIA'"""
    )
    total_mesas = int(mesas_row[0]["total_mesas"] or 0)

    processed_row = await db.execute_fetchall(
        """SELECT COUNT(*) AS total
           FROM e14_results
           WHERE corporacion = 'CAM' AND status IN ('processed', 'corrected')"""
    )
    mesas_reportadas = int(processed_row[0]["total"] or 0)

    raw_party_rows = await db.execute_fetchall(
        """SELECT party_name, SUM(votes) AS votes
           FROM party_votes
           WHERE corporacion = 'CAM'
           GROUP BY party_name
           HAVING SUM(votes) > 0
           ORDER BY votes DESC, party_name"""
    )
    votes_current: defaultdict[str, int] = defaultdict(int)
    for row in raw_party_rows:
        normalized = _normalize_party_name(str(row["party_name"] or ""))
        mapped = _map_party_for_dashboard(normalized)
        if not mapped:
            continue
        votes_current[mapped] += int(row["votes"] or 0)
    for preferred_party in _PREFERRED_PARTIES:
        votes_current.setdefault(preferred_party, 0)

    votes_current_dict = dict(votes_current)
    parties_ordered = _ordered_parties(votes_current_dict)
    curules_total = CAMARA_CURULES_ANTIOQUIA

    current_calc = _compute_curules(votes_current_dict, curules_total)
    projection_scale = (total_mesas / mesas_reportadas) if mesas_reportadas > 0 else 1.0
    projected_votes = {
        party: int(round(votes * projection_scale))
        for party, votes in votes_current_dict.items()
    }
    projected_calc = _compute_curules(projected_votes, curules_total)

    party_palette = _build_party_palette(parties_ordered)
    total_votes_current = current_calc["total_votes"]
    parties_payload = []
    for party in parties_ordered:
        votes = votes_current.get(party, 0)
        vote_share_pct = (votes / total_votes_current * 100) if total_votes_current else 0.0
        parties_payload.append(
            {
                "party_name": party,
                "votes": votes,
                "vote_share_pct": round(vote_share_pct, 2),
                "curules_current": current_calc["seat_counts"].get(party, 0),
                "projected_votes": projected_votes.get(party, 0),
                "curules_projected": projected_calc["seat_counts"].get(party, 0),
                "color": party_palette.get(party, "#5f6a72"),
                "logo_file": _PARTY_LOGOS.get(party),
                "is_pacto_historico": party == "PACTO HISTORICO",
            }
        )

    # Build timeline from CAM processed order.
    mesa_rows = await db.execute_fetchall(
        """SELECT municipio_cod, zona_cod, puesto_cod, mesa, processed_at
           FROM e14_results
           WHERE corporacion = 'CAM' AND status IN ('processed', 'corrected')
           ORDER BY
             CASE WHEN processed_at IS NULL OR processed_at = '' THEN 1 ELSE 0 END,
             datetime(processed_at),
             municipio_cod, zona_cod, puesto_cod, mesa"""
    )
    party_vote_rows = await db.execute_fetchall(
        """SELECT municipio_cod, zona_cod, puesto_cod, mesa, party_name, votes
           FROM party_votes
           WHERE corporacion = 'CAM' AND votes > 0"""
    )

    votes_by_mesa: dict[tuple[str, str, str, int], dict[str, int]] = {}
    for row in party_vote_rows:
        key = (row["municipio_cod"], row["zona_cod"], row["puesto_cod"], int(row["mesa"]))
        party_map = votes_by_mesa.setdefault(key, {})
        party_name = row["party_name"]
        party_map[party_name] = party_map.get(party_name, 0) + int(row["votes"] or 0)

    tracked_parties = [party for party in _PREFERRED_PARTIES if votes_current_dict.get(party, 0) > 0][:6]
    if len(tracked_parties) < 6:
        for party in parties_ordered:
            if party not in tracked_parties:
                tracked_parties.append(party)
            if len(tracked_parties) >= 6:
                break
    timeline: list[dict] = []
    cumulative_votes: defaultdict[str, int] = defaultdict(int)
    timeline_target = max(1, CAMARA_TIMELINE_POINTS)
    step = max(1, mesas_reportadas // timeline_target) if mesas_reportadas else 1

    for idx, row in enumerate(mesa_rows, start=1):
        key = (row["municipio_cod"], row["zona_cod"], row["puesto_cod"], int(row["mesa"]))
        for party_name, votes in votes_by_mesa.get(key, {}).items():
            normalized = _normalize_party_name(party_name)
            mapped = _map_party_for_dashboard(normalized)
            if not mapped:
                continue
            cumulative_votes[mapped] += votes

        include_point = idx == 1 or idx == mesas_reportadas or idx % step == 0
        if not include_point:
            continue

        point_calc = _compute_curules(dict(cumulative_votes), curules_total)
        timeline.append(
            {
                "mesas_reportadas": idx,
                "coverage_pct": round((idx / total_mesas * 100) if total_mesas else 0.0, 2),
                "timestamp": row["processed_at"],
                "party_votes": {party: cumulative_votes.get(party, 0) for party in tracked_parties},
                "party_curules": {
                    party: point_calc["seat_counts"].get(party, 0) for party in tracked_parties
                },
            }
        )

    return {
        "curules_total": curules_total,
        "mesas_total": total_mesas,
        "mesas_reportadas": mesas_reportadas,
        "coverage_pct": round((mesas_reportadas / total_mesas * 100) if total_mesas else 0.0, 2),
        "projection_scale": round(projection_scale, 4),
        "total_votes_current": total_votes_current,
        "cociente_electoral_current": round(current_calc["cociente_electoral"], 2),
        "threshold_votes_current": round(current_calc["threshold_votes"], 2),
        "parties": parties_payload,
        "tracked_parties": tracked_parties,
        "seat_order_current": current_calc["seat_order"],
        "seat_order_visual_current": _build_visual_seat_order(
            current_calc["seat_counts"], votes_current_dict, curules_total
        ),
        "seat_order_projected": projected_calc["seat_order"],
        "seat_order_visual_projected": _build_visual_seat_order(
            projected_calc["seat_counts"], projected_votes, curules_total
        ),
        "timeline": timeline,
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

async def get_next_unvalidated(username: str) -> dict | None:
    """Return the item claimed by this user, or claim the next available one."""
    db = await get_db()

    # 1. Return existing claim for this user if any
    claimed = await db.execute_fetchall(
        """
        SELECT r.municipio_cod, r.zona_cod, r.puesto_cod, r.mesa,
               r.corporacion, r.ph_total_votos, r.ph_votos_lista,
               r.votos_urna, r.ocr_confidence, r.processed_at,
               d.filepath,
               p.municipio, p.nombre as puesto_nombre
        FROM queue_claims qc
        JOIN e14_results r
            ON r.municipio_cod = qc.municipio_cod
            AND r.zona_cod = qc.zona_cod
            AND r.puesto_cod = qc.puesto_cod
            AND r.mesa = qc.mesa
            AND r.corporacion = qc.corporacion
        JOIN e14_downloads d ON d.id = r.download_id
        LEFT JOIN puestos p ON p.municipio_cod = r.municipio_cod
            AND p.zona_cod = r.zona_cod AND p.puesto_cod = r.puesto_cod
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
        return r

    # 2. Find next unclaimed, unvalidated item
    rows = await db.execute_fetchall(
        """
        SELECT r.municipio_cod, r.zona_cod, r.puesto_cod, r.mesa,
               r.corporacion, r.ph_total_votos, r.ph_votos_lista,
               r.votos_urna, r.ocr_confidence, r.processed_at,
               d.filepath,
               p.municipio, p.nombre as puesto_nombre
        FROM e14_results r
        JOIN e14_downloads d ON d.id = r.download_id
        LEFT JOIN puestos p ON p.municipio_cod = r.municipio_cod
            AND p.zona_cod = r.zona_cod AND p.puesto_cod = r.puesto_cod
        LEFT JOIN manual_validations mv
            ON mv.municipio_cod = r.municipio_cod
            AND mv.zona_cod = r.zona_cod
            AND mv.puesto_cod = r.puesto_cod
            AND mv.mesa = r.mesa
            AND mv.corporacion = r.corporacion
        LEFT JOIN queue_claims qc
            ON qc.municipio_cod = r.municipio_cod
            AND qc.zona_cod = r.zona_cod
            AND qc.puesto_cod = r.puesto_cod
            AND qc.mesa = r.mesa
            AND qc.corporacion = r.corporacion
        WHERE r.status IN ('processed', 'corrected')
          AND mv.id IS NULL
          AND qc.claimed_by IS NULL
        ORDER BY r.processed_at DESC
        LIMIT 1
        """
    )
    if not rows:
        return None

    r = dict(rows[0])
    mun, zona, puesto, mesa, corp = (
        r["municipio_cod"], r["zona_cod"], r["puesto_cod"], r["mesa"], r["corporacion"]
    )

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
    return r


async def release_claim(username: str):
    """Release the queue claim held by this user."""
    db = await get_db()
    await db.execute("DELETE FROM queue_claims WHERE claimed_by = ?", (username,))
    await db.commit()


async def get_validation_stats() -> dict:
    db = await get_db()
    rows = await db.execute_fetchall(
        """
        SELECT
            (SELECT COUNT(*) FROM e14_results
             WHERE status IN ('processed', 'corrected')) AS total_processed,
            (SELECT COUNT(*) FROM manual_validations) AS total_validated,
            (SELECT COUNT(*) FROM manual_validations WHERE action = 'corrected') AS total_corrected,
            (SELECT COUNT(*) FROM manual_validations WHERE novelty_note IS NOT NULL) AS total_novelty
        """
    )
    r = rows[0]
    return {
        "total_processed": r[0] or 0,
        "total_validated": r[1] or 0,
        "pending": max(0, (r[0] or 0) - (r[1] or 0)),
        "total_corrected": r[2] or 0,
        "total_novelty": r[3] or 0,
    }


async def submit_validation(data: dict):
    db = await get_db()
    mun = data["municipio_cod"]
    zona = data["zona_cod"]
    puesto = data["puesto_cod"]
    mesa = data["mesa"]
    corp = data["corporacion"]

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
            datetime.now().isoformat(),
        ),
    )

    # If corrected, update the result row
    if data["action"] == "corrected" and data.get("corrected_ph_votes") is not None:
        await db.execute(
            """
            UPDATE e14_results SET
                ph_total_votos = ?,
                status = 'corrected',
                corrected_by = ?,
                corrected_at = ?
            WHERE municipio_cod = ? AND zona_cod = ? AND puesto_cod = ?
              AND mesa = ? AND corporacion = ?
            """,
            (
                data["corrected_ph_votes"],
                data["validated_by"],
                datetime.now().isoformat(),
                mun, zona, puesto, mesa, corp,
            ),
        )

    # Release the claim so the next item can be assigned
    await db.execute(
        "DELETE FROM queue_claims WHERE claimed_by = ?",
        (data["validated_by"],),
    )

    await db.commit()


async def get_novelty_reports() -> list[dict]:
    """Return all manual validations that have a novelty note, with full mesa info."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """
        SELECT
            mv.id, mv.municipio_cod, mv.zona_cod, mv.puesto_cod, mv.mesa,
            mv.corporacion, mv.validated_by, mv.action,
            mv.corrected_ph_votes, mv.novelty_note, mv.validated_at,
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
        ORDER BY mv.validated_at DESC
        """
    )
    return [dict(r) for r in rows]


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
