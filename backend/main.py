"""ClackClack FastAPI entrypoint."""
from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from backend import database as db
from backend.config import (
    ENABLE_LOCAL_INGEST,
    ENABLE_REMOTE_POLLER,
    DASHBOARD_ACCESS_TOKEN,
    FRONTEND_DIST_DIR,
    FRONTEND_PUBLIC_DIR,
    HOST,
    PORT,
    POLL_INTERVAL,
    PUBLIC_EXPORT_SHARE_TOKEN,
    SERVE_FRONTEND,
    SFTP_POLL_INTERVAL,
    SFTP_READY,
)
from backend.routers import alerts, dashboard, manual_validate, reclamation, settings, sse, system, template, validation
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
                if new_files:
                    log.info("SFTP: %d new PDFs, sending to OCR...", len(new_files))
                    from pathlib import Path as _Path
                    tasks = [
                        ingest_file(_Path(m["local_path"]), retry_not_digitized=True)
                        for m in new_files
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    ok = sum(1 for r in results if isinstance(r, tuple) and r[0])
                    log.info("SFTP OCR done: %d/%d processed", ok, len(new_files))
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


_DASHBOARD_COOKIE = "clack_dashboard_access"
_PROTECTED_API_PREFIXES = (
    "/api/dashboard",
    "/api/alerts",
    "/api/validation",
    "/api/reclamation",
    "/api/settings",
    "/api/system",
    "/api/sse",
)
_PROTECTED_DOC_PREFIXES = ("/docs", "/redoc", "/openapi.json")


def _share_token_matches(token: str | None) -> bool:
    return bool(PUBLIC_EXPORT_SHARE_TOKEN and token and secrets.compare_digest(token, PUBLIC_EXPORT_SHARE_TOKEN))


def _dashboard_access_matches(request: Request) -> bool:
    if not DASHBOARD_ACCESS_TOKEN:
        return True

    candidates = [
        request.cookies.get(_DASHBOARD_COOKIE),
        request.headers.get("X-Dashboard-Access"),
        request.query_params.get("access"),
    ]
    return any(
        candidate and secrets.compare_digest(candidate, DASHBOARD_ACCESS_TOKEN)
        for candidate in candidates
    )


def _dashboard_cookie_requested(request: Request) -> bool:
    access = request.query_params.get("access")
    return bool(access and DASHBOARD_ACCESS_TOKEN and secrets.compare_digest(access, DASHBOARD_ACCESS_TOKEN))


def _set_dashboard_cookie(response, request: Request) -> None:
    if _dashboard_cookie_requested(request):
        response.set_cookie(
            key=_DASHBOARD_COOKIE,
            value=DASHBOARD_ACCESS_TOKEN,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=60 * 60 * 12,
        )


def _extract_share_token_from_path(request_path: str) -> str | None:
    parts = [part for part in PurePosixPath(request_path).parts if part not in {"", ".", ".."}]
    if len(parts) >= 2 and parts[0] == "descargas":
        return parts[1]
    return None


def _protected_frontend_path(full_path: str) -> bool:
    if not full_path:
        return True
    if full_path.startswith("validar"):
        return False
    if _extract_share_token_from_path(full_path):
        return False
    if "." in PurePosixPath(full_path).name:
        return False
    return True


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
app.include_router(template.router)
app.include_router(sse.router)


@app.middleware("http")
async def protect_dashboard_api(request: Request, call_next):
    path = request.url.path
    if any(path.startswith(prefix) for prefix in _PROTECTED_API_PREFIXES) or any(
        path.startswith(prefix) for prefix in _PROTECTED_DOC_PREFIXES
    ):
        if not _dashboard_access_matches(request):
            return PlainTextResponse("Not found", status_code=404)

    response = await call_next(request)
    _set_dashboard_cookie(response, request)
    return response


@app.get("/")
async def root(request: Request):
    if not _dashboard_access_matches(request):
        raise HTTPException(status_code=404)
    if SERVE_FRONTEND:
        index_path = _frontend_index()
        if index_path:
            response = FileResponse(index_path)
            _set_dashboard_cookie(response, request)
            return response
    return {
        "service": "ClackClack API",
        "status": "ok",
        "docs": "/docs",
        "frontend_served": SERVE_FRONTEND,
        "local_ingest_enabled": ENABLE_LOCAL_INGEST,
        "remote_poller_enabled": ENABLE_REMOTE_POLLER,
    }


@app.get("/{full_path:path}", include_in_schema=False)
async def frontend_fallback(full_path: str, request: Request):
    if full_path.startswith(("api/", "docs", "redoc", "openapi.json")):
        raise HTTPException(status_code=404)
    if not SERVE_FRONTEND:
        raise HTTPException(status_code=404)

    share_token = _extract_share_token_from_path(full_path)
    if share_token is not None and not _share_token_matches(share_token):
        raise HTTPException(status_code=404)
    if _protected_frontend_path(full_path) and not _dashboard_access_matches(request):
        raise HTTPException(status_code=404)

    asset_path = _resolve_frontend_asset(full_path)
    if asset_path:
        return FileResponse(asset_path)

    if "." not in PurePosixPath(full_path).name:
        index_path = _frontend_index()
        if index_path:
            response = FileResponse(index_path)
            _set_dashboard_cookie(response, request)
            return response

    raise HTTPException(status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=True)
