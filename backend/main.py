"""ClackClack FastAPI entrypoint."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend import database as db
from backend.config import (
    ENABLE_LOCAL_INGEST,
    ENABLE_REMOTE_POLLER,
    FRONTEND_DIST_DIR,
    FRONTEND_PUBLIC_DIR,
    HOST,
    PORT,
    POLL_INTERVAL,
    SERVE_FRONTEND,
    SFTP_POLL_INTERVAL,
    SFTP_READY,
)
from backend.routers import alerts, dashboard, manual_validate, reclamation, settings, sse, system, validation
from backend.services.comisiones_loader import load as load_comisiones
from backend.services.divipole_loader import load as load_divipole


async def _sftp_poll_loop(stop_event: asyncio.Event):
    """Polls SFTP for new PDFs, then hands off to local ingest pipeline."""
    import logging
    log = logging.getLogger("sftp_poller")

    from backend.services.sftp_downloader import download_new_pdfs
    from backend.services.local_ingest import ingest_file

    while not stop_event.is_set():
        if not SFTP_READY:
            log.info("SFTP not configured — set SFTP_HOST, SFTP_USER, SFTP_PASS to enable.")
        else:
            try:
                new_files = await download_new_pdfs()
                for meta in new_files:
                    from pathlib import Path
                    await ingest_file(Path(meta["local_path"]))
            except Exception as exc:
                log.error("SFTP poll error: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SFTP_POLL_INTERVAL)
        except asyncio.TimeoutError:
            continue


async def _initial_scan_task():
    try:
        from backend.services.local_ingest import scan_local_downloads

        await scan_local_downloads()
    except Exception as exc:
        from backend.services.event_bus import event_bus

        await event_bus.publish("scan_error", {"error": str(exc), "source": "initial_scan"})


def _safe_frontend_file(root: Path, relative_path: str) -> Path | None:
    candidate = root
    for part in PurePosixPath(relative_path).parts:
        if part in {"", ".", ".."}:
            continue
        candidate = candidate / part

    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _frontend_index() -> Path | None:
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.exists():
        return index_path
    return None


def _resolve_frontend_asset(request_path: str) -> Path | None:
    normalized = request_path.lstrip("/")
    for root in (FRONTEND_DIST_DIR, FRONTEND_PUBLIC_DIR):
        file_path = _safe_frontend_file(root, normalized)
        if file_path:
            return file_path
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    await db.rebuild_party_votes_index()
    await load_divipole()
    await load_comisiones()

    app.state.stop_event = asyncio.Event()
    app.state.tasks = []

    if ENABLE_LOCAL_INGEST:
        from backend.services.local_ingest import local_watch_loop

        app.state.initial_scan = {"status": "scheduled"}
        app.state.tasks.append(asyncio.create_task(_initial_scan_task()))
        app.state.tasks.append(asyncio.create_task(local_watch_loop(app.state.stop_event)))
    else:
        app.state.initial_scan = {"status": "disabled"}

    if ENABLE_REMOTE_POLLER:
        from backend.services.remote_poller import remote_poller

        app.state.tasks.append(asyncio.create_task(remote_poller.loop(app.state.stop_event)))

    # SFTP poller — starts if credentials are configured, otherwise logs and waits
    app.state.tasks.append(asyncio.create_task(_sftp_poll_loop(app.state.stop_event)))

    try:
        yield
    finally:
        app.state.stop_event.set()
        for task in app.state.tasks:
            task.cancel()
        await asyncio.gather(*app.state.tasks, return_exceptions=True)
        await db.close_db()


app = FastAPI(
    title="ClackClack API",
    description="Dashboard y escrutinio E14 Antioquia 2026",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(alerts.router)
app.include_router(validation.router)
app.include_router(manual_validate.router)
app.include_router(reclamation.router)
app.include_router(settings.router)
app.include_router(system.router)
app.include_router(sse.router)


@app.get("/")
async def root():
    if SERVE_FRONTEND:
        index_path = _frontend_index()
        if index_path:
            return FileResponse(index_path)
    return {
        "service": "ClackClack API",
        "status": "ok",
        "docs": "/docs",
        "frontend_served": SERVE_FRONTEND,
        "local_ingest_enabled": ENABLE_LOCAL_INGEST,
        "remote_poller_enabled": ENABLE_REMOTE_POLLER,
    }


@app.get("/{full_path:path}", include_in_schema=False)
async def frontend_fallback(full_path: str):
    if full_path.startswith(("api/", "docs", "redoc", "openapi.json")):
        raise HTTPException(status_code=404)
    if not SERVE_FRONTEND:
        raise HTTPException(status_code=404)

    asset_path = _resolve_frontend_asset(full_path)
    if asset_path:
        return FileResponse(asset_path)

    if "." not in PurePosixPath(full_path).name:
        index_path = _frontend_index()
        if index_path:
            return FileResponse(index_path)

    raise HTTPException(status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=True)
