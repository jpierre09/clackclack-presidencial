"""SFTP downloader for E-14 PDFs from Registraduría SFTP server.

Estructura del servidor:
  /cargue/Corte_XXX/Corte_XXX_{dept}.tar.gz
  Dentro del tar: {dept}/{mun}/{zona3}/{puesto2}/{mesa3}/{CORP}/E14_*.pdf

Credenciales via env vars:
  SFTP_HOST=e14.registraduria.gov.co  SFTP_PORT=444
  SFTP_USER=...  SFTP_PASS=...
  SFTP_PATH=/cargue  (raíz del servidor)
"""
from __future__ import annotations

import asyncio
import logging
import re
import tarfile
import tempfile
from pathlib import Path

from backend.config import (
    DEPT_CODE,
    E14_DOWNLOADS_DIR,
    SFTP_HOST, SFTP_PORT, SFTP_USER, SFTP_PASS, SFTP_KEY_PATH, SFTP_PATH,
    SFTP_READY,
)
from backend import database as db

log = logging.getLogger(__name__)
SYNC_LOCK = asyncio.Lock()

# Archivo de estado: qué cortes ya se descargaron completamente
_STATE_FILE = E14_DOWNLOADS_DIR.parent / "sftp_cortes_state.json"

DEPT_FILTER = DEPT_CODE if DEPT_CODE not in ("ALL", "") else "01"


def _normalize_remote_root(raw_path: str) -> str:
    candidate = (raw_path or "/cargue").strip().replace("\\", "/").rstrip("/") or "/cargue"
    if re.match(r"^[A-Za-z]:/", candidate):
        tail = candidate.split("/")[-1]
        candidate = f"/{tail}" if tail else "/cargue"
    if not candidate.startswith("/"):
        candidate = f"/{candidate.lstrip('/')}"
    return candidate or "/cargue"


REMOTE_ROOT = _normalize_remote_root(SFTP_PATH)
if not REMOTE_ROOT.startswith("/"):
    REMOTE_ROOT = f"/{REMOTE_ROOT.lstrip('/')}"
SKIP_STATUSES = {"processed", "corrected", "error"}


def _normalize_zona(zona3: str) -> str:
    return str(int(zona3)).zfill(2)


def _result_key(info: dict) -> tuple[str, str, str, int, str]:
    return (
        info["municipio_cod"],
        info["zona_cod"],
        info["puesto_cod"],
        info["mesa"],
        info["corporacion"],
    )


def _parse_sftp_path(path: str) -> dict | None:
    """01/MUN/ZONA/PUESTO/MESA/CORP/filename → dict con claves DB."""
    parts = path.strip("/").split("/")
    if len(parts) < 6:
        return None
    dept, mun, zona3, puesto, mesa_str, corp = parts[:6]
    if corp.upper() not in ("PRES", "PRE", "PRESIDENCIAL"):
        return None
    try:
        return {
            "municipio_cod": mun,
            "zona_cod": _normalize_zona(zona3),
            "puesto_cod": puesto,
            "mesa": int(mesa_str),
            "corporacion": corp,
        }
    except ValueError:
        return None


def _load_state() -> dict[str, dict]:
    """Carga el estado del SFTP.

    Compatibilidad:
    - formato nuevo: {"Corte_001": {"size": 123, "mtime": 456}}
    - formato legacy: ["Corte_001", "Corte_002"]
    """
    import json
    if _STATE_FILE.exists():
        try:
            raw = json.loads(_STATE_FILE.read_text())
            if isinstance(raw, dict):
                state: dict[str, dict] = {}
                for corte, meta in raw.items():
                    if isinstance(meta, dict):
                        state[str(corte)] = {
                            "size": int(meta.get("size") or 0),
                            "mtime": int(meta.get("mtime") or 0),
                            "legacy": bool(meta.get("legacy", False)),
                        }
                    else:
                        state[str(corte)] = {"legacy": True}
                return state
            if isinstance(raw, list):
                return {str(corte): {"legacy": True} for corte in raw}
        except Exception:
            pass
    return {}


def _save_state(state: dict[str, dict]):
    import json
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, sort_keys=True))


def clear_state():
    """Forget cached corte signatures so the next cycle re-checks the SFTP."""
    _STATE_FILE.unlink(missing_ok=True)


def _remote_signature(stat_result) -> dict[str, int]:
    return {
        "size": int(getattr(stat_result, "st_size", 0) or 0),
        "mtime": int(getattr(stat_result, "st_mtime", 0) or 0),
    }


def _same_signature(saved: dict | None, current: dict[str, int]) -> bool:
    if not saved or saved.get("legacy"):
        return False
    return (
        int(saved.get("size") or 0) == current["size"]
        and int(saved.get("mtime") or 0) == current["mtime"]
    )


def _resolve_remote_archive(sftp, corte_name: str) -> tuple[str, object] | tuple[None, None]:
    candidates = (
        f"{REMOTE_ROOT}/{corte_name}/{corte_name}_{DEPT_FILTER}.tar.gz",
        f"{REMOTE_ROOT}/{corte_name}/{corte_name}.tar.gz",
    )
    for remote_path in candidates:
        try:
            return remote_path, sftp.stat(remote_path)
        except FileNotFoundError:
            continue
    return None, None


def _local_path_for(info: dict, filename: str) -> Path:
    """Construye la ruta local donde se guarda el PDF."""
    dept = DEPT_FILTER
    mun  = info["municipio_cod"]
    zon  = info["zona_cod"]
    pue  = info["puesto_cod"]
    mes  = info["mesa"]
    corp = info["corporacion"]

    sub = (
        E14_DOWNLOADS_DIR
        / f"{dept}-ANTIOQUIA"
        / f"{mun}-MUN"
        / f"{zon}-Zona {zon}"
        / f"{pue}-PUESTO"
    )
    sub.mkdir(parents=True, exist_ok=True)
    return sub / f"MESA_{mes:03d}_{corp}_{filename}"


async def _load_existing_statuses() -> dict[tuple[str, str, str, int, str], str]:
    """Carga el estado actual por mesa/corporación para decidir qué reintentar."""
    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT municipio_cod, zona_cod, puesto_cod, mesa, corporacion, status
           FROM e14_results"""
    )
    return {
        (
            row["municipio_cod"],
            row["zona_cod"],
            row["puesto_cod"],
            row["mesa"],
            row["corporacion"],
        ): row["status"]
        for row in rows
    }


def _sync_download_corte(
    sftp,
    corte_name: str,
    result_statuses: dict[tuple[str, str, str, int, str], str],
    remote_path: str,
    size_bytes: int,
) -> list[dict]:
    """Descarga y extrae un corte. Devuelve PDFs pendientes listos para ingestión."""
    dept = DEPT_FILTER
    dept_file = f"{corte_name}_{dept}.tar.gz"
    size_mb = size_bytes / 1024 / 1024
    log.info("Descargando %s (%.1f MB)...", remote_path, size_mb)

    pending_files: list[dict] = []
    skipped_existing = 0
    tmp_tar = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp_tar.close()
    try:
        sftp.get(remote_path, tmp_tar.name)
        log.info("%s descargado OK", dept_file)

        with tarfile.open(tmp_tar.name, mode="r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                if "/SEN/" not in member.name and "/CAM/" not in member.name:
                    continue

                info = _parse_sftp_path(member.name)
                if not info:
                    continue
                key = _result_key(info)
                if result_statuses.get(key) in SKIP_STATUSES:
                    skipped_existing += 1
                    continue

                filename = Path(member.name).name
                local = _local_path_for(info, filename)

                fobj = tf.extractfile(member)
                if fobj:
                    local.write_bytes(fobj.read())
                    pending_files.append({**info, "filename": filename, "local_path": str(local)})
                    result_statuses[key] = "queued"
    finally:
        Path(tmp_tar.name).unlink(missing_ok=True)

    log.info(
        "%s: %d PDFs listos para ingestión (%d omitidos por estado existente)",
        corte_name,
        len(pending_files),
        skipped_existing,
    )
    return pending_files


async def download_new_pdfs() -> list[dict]:
    """Descarga PDFs nuevos de todos los cortes pendientes del SFTP.

    Retorna lista de dicts con {local_path, municipio_cod, zona_cod,
    puesto_cod, mesa, corporacion} para cada PDF nuevo.
    """
    if not SFTP_READY:
        log.info("SFTP no configurado — set SFTP_HOST, SFTP_USER, SFTP_PASS")
        return []

    if SYNC_LOCK.locked():
        log.info("SFTP sync ya en ejecución; esperando el ciclo actual")

    async with SYNC_LOCK:
        try:
            import paramiko
        except ImportError:
            log.error("paramiko no instalado")
            return []

        E14_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        corte_state = _load_state()
        result_statuses = await _load_existing_statuses()

        def _sync_run() -> list[dict]:
            transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
            if SFTP_KEY_PATH:
                key = paramiko.RSAKey.from_private_key_file(SFTP_KEY_PATH)
                transport.connect(username=SFTP_USER, pkey=key)
            else:
                transport.connect(username=SFTP_USER, password=SFTP_PASS)

            sftp = paramiko.SFTPClient.from_transport(transport)
            results: list[dict] = []

            try:
                cortes = sorted(sftp.listdir(REMOTE_ROOT), reverse=True)
            except Exception as e:
                log.error("SFTP listdir %s: %s", REMOTE_ROOT, e)
                sftp.close(); transport.close()
                return results

            for corte in cortes:
                remote_path, stat_result = _resolve_remote_archive(sftp, corte)
                if not remote_path or stat_result is None:
                    log.info("%s: sin archivo para dept %s", corte, DEPT_FILTER)
                    continue

                remote_sig = _remote_signature(stat_result)
                saved_sig = corte_state.get(corte)
                if saved_sig and saved_sig.get("legacy"):
                    corte_state[corte] = remote_sig
                    _save_state(corte_state)
                    log.info("%s: estado legacy migrado", corte)
                    continue
                if _same_signature(saved_sig, remote_sig):
                    log.info("%s: sin cambios remotos, saltando", corte)
                    continue

                new_files = _sync_download_corte(
                    sftp,
                    corte,
                    result_statuses,
                    remote_path=remote_path,
                    size_bytes=remote_sig["size"],
                )
                results.extend(new_files)

                corte_state[corte] = remote_sig
                _save_state(corte_state)

            sftp.close()
            transport.close()
            return results

        loop = asyncio.get_event_loop()
        try:
            downloaded = await loop.run_in_executor(None, _sync_run)
            log.info("SFTP sync completo: %d PDFs nuevos", len(downloaded))
        except Exception as e:
            log.error("SFTP error: %s", e)
            downloaded = []

        return downloaded
