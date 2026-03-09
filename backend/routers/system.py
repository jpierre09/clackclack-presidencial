"""Operational endpoints for scans/poller health."""
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from backend.config import (
    DEPT_CODE,
    E14_DOWNLOADS_DIR,
    ENABLE_LOCAL_INGEST,
    ENABLE_REMOTE_POLLER,
    SERVE_FRONTEND,
    SFTP_HOST,
    SFTP_POLL_INTERVAL,
    SFTP_READY,
)
from backend.services.event_bus import event_bus

router = APIRouter(prefix="/api/system", tags=["system"])


@router.post("/rescan")
async def trigger_rescan(limit: int | None = None):
    if not ENABLE_LOCAL_INGEST:
        return {"status": "disabled", "reason": "local_ingest_disabled"}

    from backend.services.local_ingest import scan_local_downloads

    stats = await scan_local_downloads(limit=limit)
    return {"status": "ok", "scan": stats}


@router.post("/poll-once")
async def remote_poll_once():
    if not ENABLE_REMOTE_POLLER:
        return {"status": "disabled", "reason": "remote_poller_disabled"}

    from backend.services.remote_poller import remote_poller

    stats = await remote_poller.poll_once()
    return {"status": "ok", "poll": stats}


@router.post("/sftp-sync")
async def sftp_sync():
    """Manually trigger an SFTP download cycle."""
    if not SFTP_READY:
        return {
            "status": "waiting",
            "reason": "SFTP credentials not configured. Set SFTP_HOST, SFTP_USER, SFTP_PASS.",
        }

    from backend.services.sftp_downloader import download_new_pdfs
    from backend.services.local_ingest import ingest_file
    from pathlib import Path

    new_files = await download_new_pdfs()
    processed = 0
    for meta in new_files:
        ok, _ = await ingest_file(Path(meta["local_path"]))
        if ok:
            processed += 1

    return {"status": "ok", "downloaded": len(new_files), "processed": processed}


@router.post("/upload-e14")
async def upload_e14(
    file: UploadFile = File(...),
    dept_code: str = Form(...),   # e.g. "29"
    mun_code: str = Form(...),    # e.g. "001"
    zona_code: str = Form(...),   # e.g. "01"
    puesto_code: str = Form(...), # e.g. "01"
    mesa: int = Form(...),        # e.g. 3
    corp: str = Form(...),        # "SEN" | "CAM"
):
    """Accept a PDF upload and ingest it as if it came from SFTP."""
    from pathlib import Path
    from backend.services.local_ingest import ingest_file

    corp = corp.upper()
    if corp not in ("SEN", "CAM"):
        raise HTTPException(status_code=400, detail="corp must be SEN or CAM")

    dest_dir = (
        E14_DOWNLOADS_DIR
        / f"{dept_code}-UPLOAD"
        / f"{mun_code}-MUN"
        / f"{zona_code}-Zona {zona_code}"
        / f"{puesto_code}-PUESTO"
    )
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Keep original filename or build a canonical one
    original_name = file.filename or f"MESA_{mesa:03d}_{corp}_upload.pdf"
    if not original_name.upper().startswith("MESA_"):
        original_name = f"MESA_{mesa:03d}_{corp}_{original_name}"

    dest_path = dest_dir / original_name
    content = await file.read()
    dest_path.write_bytes(content)

    ok, reason = await ingest_file(dest_path)
    return {
        "status": "ok" if ok else "skipped",
        "reason": reason,
        "path": str(dest_path.relative_to(E14_DOWNLOADS_DIR)),
        "size_kb": round(len(content) / 1024, 1),
    }


@router.get("/ocr-errors")
async def ocr_errors():
    """Show top OCR error messages grouped by type."""
    from backend import database as db
    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT corporacion, error_message, COUNT(*) as n,
                  MAX(processed_at) as last_at
           FROM e14_results WHERE status='error'
           GROUP BY corporacion, error_message
           ORDER BY n DESC LIMIT 20"""
    )
    return [dict(r) for r in rows]


@router.post("/reset-key-state")
async def reset_key_state():
    """Clear the Claude API key exhaustion state so rotation resets."""
    from backend.services.claude_ocr import _BASE
    state_file = _BASE / "ClaudeKeyState.json"
    if state_file.exists():
        state_file.unlink()
    return {"status": "ok", "message": "ClaudeKeyState.json eliminado — rotación de claves reseteada"}


@router.post("/retry-errors")
async def retry_errors(limit: int = 20):
    """Delete error-status results so they can be re-processed on next rescan."""
    from backend import database as db
    conn = await db.get_db()
    await conn.execute(
        "DELETE FROM e14_results WHERE status='error' LIMIT ?", (limit,)
    )
    await conn.commit()
    result = await conn.execute_fetchall("SELECT changes() as n")
    return {"deleted": result[0]["n"] if result else 0}


@router.post("/retry-not-digitized")
async def retry_not_digitized():
    """Delete not_digitized records + their PDF files so the poller re-downloads them when Registraduría has digitized them."""
    from pathlib import Path as _Path
    from backend import database as db

    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT r.id as result_id, r.download_id, d.filepath
           FROM e14_results r
           LEFT JOIN e14_downloads d ON d.id = r.download_id
           WHERE r.status = 'not_digitized'"""
    )

    deleted_files = 0
    for row in rows:
        fp = row["filepath"]
        if fp:
            try:
                _Path(fp).unlink(missing_ok=True)
                deleted_files += 1
            except Exception:
                pass

    result_ids = [r["result_id"] for r in rows]
    download_ids = [r["download_id"] for r in rows if r["download_id"]]

    # Delete results first (FK references downloads), then downloads
    if result_ids:
        ph = ",".join("?" * len(result_ids))
        await conn.execute(f"DELETE FROM e14_results WHERE id IN ({ph})", result_ids)
    if download_ids:
        ph = ",".join("?" * len(download_ids))
        await conn.execute(f"DELETE FROM e14_downloads WHERE id IN ({ph})", download_ids)

    await conn.commit()
    return {
        "deleted_records": len(result_ids),
        "deleted_files": deleted_files,
        "message": f"{len(result_ids)} PDFs eliminados — serán re-descargados en el próximo ciclo del poller.",
    }


async def _do_scan_not_digitized():
    """Background worker: checks all PDFs for not-digitized placeholder pages."""
    import asyncio
    from pathlib import Path as _Path
    from backend import database as db
    from backend.services.ocr_processor import _page_is_not_digitized, _pages_for

    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT r.id as result_id, r.download_id, r.corporacion, d.filepath
           FROM e14_results r
           LEFT JOIN e14_downloads d ON d.id = r.download_id
           WHERE r.status IN ('processed', 'error')
             AND d.filepath IS NOT NULL"""
    )

    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(16)
    found_ids: list[tuple[int, int, str]] = []

    async def _check(row):
        fp = row["filepath"]
        if not fp:
            return
        if not _Path(fp).exists():
            return
        start_page, _ = _pages_for(row["corporacion"])
        async with sem:
            is_nd = await loop.run_in_executor(
                None, lambda: _page_is_not_digitized(fp, start_page)
            )
        if is_nd:
            found_ids.append((row["result_id"], row["download_id"], fp))

    await asyncio.gather(*[_check(r) for r in rows])

    for result_id, download_id, fp in found_ids:
        await conn.execute(
            "UPDATE e14_results SET status='not_digitized', error_message=? WHERE id=?",
            ("Página no digitalizada por la Registraduría", result_id)
        )
        try:
            _Path(fp).unlink(missing_ok=True)
        except Exception:
            pass
        await conn.execute("DELETE FROM e14_downloads WHERE id=?", (download_id,))

    if found_ids:
        await conn.commit()


@router.post("/scan-not-digitized")
async def scan_not_digitized(background_tasks: BackgroundTasks):
    """Start a background scan of all downloaded PDFs to detect 'not digitized'
    placeholder pages without calling the Claude API. Check /not-digitized-count
    after a minute to see results."""
    background_tasks.add_task(_do_scan_not_digitized)
    return {"status": "started", "message": "Escaneo iniciado en background. Revisa /api/system/not-digitized-count en ~1 minuto."}


async def _do_scan_novedades_not_digitized():
    """Background worker: checks PDFs behind novelty reports for 'not digitized' pages.
    Deletes the novelty, OCR result, download record and PDF so the poller re-fetches."""
    import asyncio
    from pathlib import Path as _Path
    from backend import database as db
    from backend.services.ocr_processor import _page_is_not_digitized, _pages_for

    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT mv.id as mv_id, mv.municipio_cod, mv.zona_cod, mv.puesto_cod,
                  mv.mesa, mv.corporacion,
                  r.id as result_id, r.download_id,
                  d.filepath
           FROM manual_validations mv
           JOIN e14_results r ON (
               r.municipio_cod = mv.municipio_cod AND
               r.zona_cod      = mv.zona_cod      AND
               r.puesto_cod    = mv.puesto_cod    AND
               r.mesa          = mv.mesa          AND
               r.corporacion   = mv.corporacion
           )
           LEFT JOIN e14_downloads d ON d.id = r.download_id
           WHERE mv.action = 'novelty'"""
    )

    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(16)

    # Store all needed data as a dict in the found list
    found: list[dict] = []

    async def _check(row):
        fp = row["filepath"]
        if not fp or not _Path(fp).exists():
            return
        start_page, _ = _pages_for(row["corporacion"])
        async with sem:
            is_nd = await loop.run_in_executor(
                None, lambda: _page_is_not_digitized(fp, start_page)
            )
        if is_nd:
            found.append({
                "mv_id": row["mv_id"],
                "result_id": row["result_id"],
                "download_id": row["download_id"],
                "fp": fp,
                "municipio_cod": row["municipio_cod"],
                "zona_cod": row["zona_cod"],
                "puesto_cod": row["puesto_cod"],
                "mesa": row["mesa"],
                "corporacion": row["corporacion"],
            })

    await asyncio.gather(*[_check(r) for r in rows])

    for item in found:
        # 1. Release any queue claims for this item
        await conn.execute(
            """DELETE FROM queue_claims
               WHERE municipio_cod=? AND zona_cod=? AND puesto_cod=? AND mesa=? AND corporacion=?""",
            (item["municipio_cod"], item["zona_cod"], item["puesto_cod"],
             item["mesa"], item["corporacion"])
        )
        # 2. Delete the novelty report
        await conn.execute("DELETE FROM manual_validations WHERE id = ?", (item["mv_id"],))
        # 3. Delete OCR result (FK: must go before download)
        await conn.execute("DELETE FROM e14_results WHERE id = ?", (item["result_id"],))
        # 4. Delete download record
        if item["download_id"]:
            await conn.execute("DELETE FROM e14_downloads WHERE id = ?", (item["download_id"],))
        # 5. Remove PDF from disk
        try:
            _Path(item["fp"]).unlink(missing_ok=True)
        except Exception:
            pass

    if found:
        await conn.commit()


@router.get("/debug-novedades-scan")
async def debug_novedades_scan():
    """Diagnostic: show first 5 novelty PDFs with their file status and whiteness ratio."""
    import asyncio
    from pathlib import Path as _Path
    import fitz
    from backend import database as db
    from backend.services.ocr_processor import _pages_for

    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT mv.id as mv_id, mv.novelty_note, mv.corporacion,
                  r.id as result_id, r.status as r_status,
                  d.filepath
           FROM manual_validations mv
           JOIN e14_results r ON (
               r.municipio_cod = mv.municipio_cod AND r.zona_cod = mv.zona_cod AND
               r.puesto_cod = mv.puesto_cod AND r.mesa = mv.mesa AND
               r.corporacion = mv.corporacion
           )
           LEFT JOIN e14_downloads d ON d.id = r.download_id
           WHERE mv.action = 'novelty'
           LIMIT 10"""
    )

    results = []
    for row in rows:
        fp = row["filepath"]
        entry = {
            "mv_id": row["mv_id"], "note": row["novelty_note"],
            "corp": row["corporacion"], "r_status": row["r_status"],
            "filepath": fp, "file_exists": False,
            "white_ratio": None, "bottom_white_ratio": None,
        }
        if fp:
            p = _Path(fp)
            entry["file_exists"] = p.exists()
            if p.exists():
                try:
                    start_page, _ = _pages_for(row["corporacion"])
                    doc = fitz.open(fp)
                    num_pages = len(doc)
                    pi = start_page if start_page < num_pages else 0
                    page = doc[pi]
                    mat = fitz.Matrix(0.25, 0.25)
                    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
                    h, w = pix.height, pix.width
                    samples = bytes(pix.samples)
                    doc.close()
                    white_px = sum(1 for b in samples if b > 210)
                    entry["white_ratio"] = round(white_px / len(samples), 3)
                    bottom_start = int(h * 0.60) * w
                    bs = samples[bottom_start:]
                    if bs:
                        entry["bottom_white_ratio"] = round(sum(1 for b in bs if b > 210) / len(bs), 3)
                    entry["num_pages"] = num_pages
                    entry["page_checked"] = pi
                except Exception as e:
                    entry["error"] = str(e)
        results.append(entry)
    return results


@router.post("/scan-novedades-not-digitized")
async def scan_novedades_not_digitized():
    """Scan PDFs behind novelty reports and delete those showing 'PÁGINA NO DIGITALIZADA'."""
    await _do_scan_novedades_not_digitized()
    from backend import database as db
    conn = await db.get_db()
    remaining = await conn.execute_fetchall(
        "SELECT COUNT(*) as n FROM manual_validations WHERE action='novelty'"
    )
    return {
        "status": "done",
        "remaining_novedades": remaining[0]["n"] if remaining else 0,
    }


@router.get("/not-digitized-count")
async def not_digitized_count():
    """Count PDFs that Registraduría hasn't digitized yet."""
    from backend import database as db
    conn = await db.get_db()
    rows = await conn.execute_fetchall(
        """SELECT corporacion, COUNT(*) as n
           FROM e14_results WHERE status = 'not_digitized'
           GROUP BY corporacion ORDER BY n DESC"""
    )
    total = sum(r["n"] for r in rows)
    return {"total": total, "by_corp": [dict(r) for r in rows]}


@router.get("/status")
async def status():
    return {
        "subscribers": event_bus.subscriber_count(),
        "mode": {
            "frontend_served": SERVE_FRONTEND,
            "local_ingest_enabled": ENABLE_LOCAL_INGEST,
            "remote_poller_enabled": ENABLE_REMOTE_POLLER,
            "sftp_ready": SFTP_READY,
            "sftp_host": SFTP_HOST or None,
            "sftp_poll_interval_s": SFTP_POLL_INTERVAL,
            "dept_code_filter": DEPT_CODE,
        },
    }
