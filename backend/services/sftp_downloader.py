"""SFTP downloader for E-14 PDFs from Registraduría SFTP server.

Credentials are read from environment variables:
  SFTP_HOST, SFTP_PORT, SFTP_USER, SFTP_PASS or SFTP_KEY_PATH, SFTP_PATH

If credentials are not set, the poller logs a waiting message and skips.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from backend.config import (
    E14_DOWNLOADS_DIR,
    SFTP_HOST, SFTP_PORT, SFTP_USER, SFTP_PASS, SFTP_KEY_PATH, SFTP_PATH,
    SFTP_READY,
)

log = logging.getLogger(__name__)

# Filename pattern: <id>_E14_<CORP>_X_<dept>_<mun>_<zon>_XX_<pue>_<mes>_X_XXX.pdf
_PDF_RE = re.compile(
    r"^(?P<id>\d+)_E14_(?P<corp>SEN|CAM)_X_"
    r"(?P<dept>\d+)_(?P<mun>\d+)_(?P<zon>\d+)_XX_"
    r"(?P<pue>\d+)_(?P<mes>\d+)_X_XXX\.pdf$",
    re.IGNORECASE,
)


def parse_filename(name: str) -> dict | None:
    """Extract metadata from E-14 filename. Returns None if not recognised."""
    m = _PDF_RE.match(name)
    if not m:
        return None
    return {
        "filename": name,
        "corporacion": m.group("corp").upper(),
        "departamento_cod": m.group("dept").zfill(2),
        "municipio_cod": m.group("mun").zfill(3),
        "zona_cod": m.group("zon").zfill(2),
        "puesto_cod": m.group("pue").zfill(2),
        "mesa": int(m.group("mes")),
    }


async def download_new_pdfs() -> list[dict]:
    """Connect to SFTP, download PDFs not already present locally.

    Returns list of metadata dicts for newly downloaded files.
    """
    if not SFTP_READY:
        log.info(
            "SFTP credentials not configured — waiting for "
            "SFTP_HOST, SFTP_USER, SFTP_PASS/SFTP_KEY_PATH env vars."
        )
        return []

    try:
        import paramiko
    except ImportError:
        log.error("paramiko not installed — run: pip install paramiko")
        return []

    E14_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict] = []

    def _sync_download() -> list[dict]:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = {
            "hostname": SFTP_HOST,
            "port": SFTP_PORT,
            "username": SFTP_USER,
            "timeout": 30,
        }
        if SFTP_KEY_PATH:
            connect_kwargs["key_filename"] = SFTP_KEY_PATH
        else:
            connect_kwargs["password"] = SFTP_PASS

        ssh.connect(**connect_kwargs)
        sftp = ssh.open_sftp()
        results: list[dict] = []

        try:
            remote_files = sftp.listdir(SFTP_PATH)
        except Exception as e:
            log.error("SFTP listdir error: %s", e)
            sftp.close()
            ssh.close()
            return results

        for fname in remote_files:
            if not fname.lower().endswith(".pdf"):
                continue
            meta = parse_filename(fname)
            if meta is None:
                continue

            # Save in the directory structure expected by local_ingest.py:
            # e14_downloads/{dept}-DEPT/{mun}-MUN/{zona}-Zona {zona}/{pue}-PUESTO/MESA_{mes}_{corp}_{id}.pdf
            dept = meta["departamento_cod"]
            mun  = meta["municipio_cod"]
            zon  = meta["zona_cod"]
            pue  = meta["puesto_cod"]
            mes  = meta["mesa"]
            corp = meta["corporacion"]
            fid  = fname.split("_")[0]

            sub_dir = (
                E14_DOWNLOADS_DIR
                / f"{dept}-DEPT"
                / f"{mun}-MUN"
                / f"{zon}-Zona {zon}"
                / f"{pue}-PUESTO"
            )
            sub_dir.mkdir(parents=True, exist_ok=True)
            local_path = sub_dir / f"MESA_{mes:03d}_{corp}_{fid}.pdf"

            if local_path.exists():
                continue  # Already downloaded

            remote_path = f"{SFTP_PATH.rstrip('/')}/{fname}"
            try:
                sftp.get(remote_path, str(local_path))
                log.info("Downloaded: %s → %s", fname, local_path)
                meta["local_path"] = str(local_path)
                results.append(meta)
            except Exception as e:
                log.error("Failed to download %s: %s", fname, e)
                if local_path.exists():
                    local_path.unlink()

        sftp.close()
        ssh.close()
        return results

    loop = asyncio.get_event_loop()
    try:
        downloaded = await loop.run_in_executor(None, _sync_download)
        log.info("SFTP sync: %d new PDFs downloaded", len(downloaded))
    except Exception as e:
        log.error("SFTP connection error: %s", e)

    return downloaded
