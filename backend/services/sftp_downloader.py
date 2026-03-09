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
import io
import logging
import tarfile
from pathlib import Path

from backend.config import (
    DEPT_CODE,
    E14_DOWNLOADS_DIR,
    SFTP_HOST, SFTP_PORT, SFTP_USER, SFTP_PASS, SFTP_KEY_PATH,
    SFTP_READY,
)
from backend import database as db

log = logging.getLogger(__name__)

# Archivo de estado: qué cortes ya se descargaron completamente
_STATE_FILE = E14_DOWNLOADS_DIR.parent / "sftp_cortes_state.json"

DEPT_FILTER = DEPT_CODE if DEPT_CODE not in ("ALL", "") else "01"


def _normalize_zona(zona3: str) -> str:
    return str(int(zona3)).zfill(2)


def _parse_sftp_path(path: str) -> dict | None:
    """01/MUN/ZONA/PUESTO/MESA/CORP/filename → dict con claves DB."""
    parts = path.strip("/").split("/")
    if len(parts) < 6:
        return None
    dept, mun, zona3, puesto, mesa_str, corp = parts[:6]
    if corp not in ("SEN", "CAM"):
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


def _load_state() -> set[str]:
    """Devuelve el set de cortes ya procesados."""
    import json
    if _STATE_FILE.exists():
        try:
            return set(json.loads(_STATE_FILE.read_text()))
        except Exception:
            pass
    return set()


def _save_state(done: set[str]):
    import json
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(sorted(done)))


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


async def _already_processed(info: dict) -> bool:
    """Devuelve True si ya hay un resultado processed/corrected en la DB."""
    conn = await db.get_db()
    row = await conn.execute_fetchone(
        """SELECT status FROM e14_results
           WHERE municipio_cod=? AND zona_cod=? AND puesto_cod=? AND mesa=? AND corporacion=?""",
        (info["municipio_cod"], info["zona_cod"],
         info["puesto_cod"], info["mesa"], info["corporacion"]),
    )
    if row is None:
        return False
    return row["status"] in ("processed", "corrected")


def _sync_download_corte(sftp, corte_name: str) -> list[Path]:
    """Descarga y extrae un corte. Devuelve lista de PDFs nuevos guardados."""
    dept = DEPT_FILTER
    dept_file = f"{corte_name}_{dept}.tar.gz"
    remote_path = f"/cargue/{corte_name}/{dept_file}"

    try:
        sftp.stat(remote_path)
    except FileNotFoundError:
        log.info("%s: sin archivo para dept %s", corte_name, dept)
        return []

    size_mb = sftp.stat(remote_path).st_size / 1024 / 1024
    log.info("Descargando %s (%.1f MB)...", remote_path, size_mb)

    buf = io.BytesIO()
    sftp.getfo(remote_path, buf)
    buf.seek(0)
    log.info("%s descargado OK", dept_file)

    new_files: list[Path] = []
    with tarfile.open(fileobj=buf, mode="r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            if "/SEN/" not in member.name and "/CAM/" not in member.name:
                continue

            info = _parse_sftp_path(member.name)
            if not info:
                continue

            filename = Path(member.name).name
            local = _local_path_for(info, filename)

            if local.exists():
                continue

            fobj = tf.extractfile(member)
            if fobj:
                local.write_bytes(fobj.read())
                new_files.append(local)

    log.info("%s: %d PDFs nuevos extraídos", corte_name, len(new_files))
    return new_files


async def download_new_pdfs() -> list[dict]:
    """Descarga PDFs nuevos de todos los cortes pendientes del SFTP.

    Retorna lista de dicts con {local_path, municipio_cod, zona_cod,
    puesto_cod, mesa, corporacion} para cada PDF nuevo.
    """
    if not SFTP_READY:
        log.info("SFTP no configurado — set SFTP_HOST, SFTP_USER, SFTP_PASS")
        return []

    try:
        import paramiko
    except ImportError:
        log.error("paramiko no instalado")
        return []

    E14_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    done_cortes = _load_state()

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
            cortes = sorted(sftp.listdir("/cargue"))
        except Exception as e:
            log.error("SFTP listdir /cargue: %s", e)
            sftp.close(); transport.close()
            return results

        for corte in cortes:
            if corte in done_cortes:
                log.info("%s: ya procesado, saltando", corte)
                continue

            new_files = _sync_download_corte(sftp, corte)
            for local_path in new_files:
                info = _parse_sftp_path(
                    str(local_path.relative_to(E14_DOWNLOADS_DIR))
                    .replace("\\", "/")
                )
                if info:
                    results.append({**info, "local_path": str(local_path)})

            done_cortes.add(corte)
            _save_state(done_cortes)

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
