"""Dashboard API endpoints."""
import asyncio
import time
from fastapi import APIRouter
from backend import database as db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# ── Simple TTL cache ────────────────────────────────────────────────────────
# Avoids hitting SQLite with the same heavy query from multiple concurrent tabs.
_cache: dict[str, tuple[float, object]] = {}
_cache_locks: dict[str, asyncio.Lock] = {}

def _lock_for(key: str) -> asyncio.Lock:
    if key not in _cache_locks:
        _cache_locks[key] = asyncio.Lock()
    return _cache_locks[key]

async def _cached(key: str, ttl: int, fn):
    """Return cached value if fresh, else call fn() and cache the result."""
    now = time.monotonic()
    if key in _cache:
        ts, val = _cache[key]
        if now - ts < ttl:
            return val
    async with _lock_for(key):
        # Re-check after acquiring lock (another coroutine may have refreshed)
        if key in _cache:
            ts, val = _cache[key]
            if now - ts < ttl:
                return val
        val = await fn()
        _cache[key] = (time.monotonic(), val)
        return val


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/summary")
async def get_summary():
    return await _cached("summary", 30, db.get_dashboard_summary)


@router.get("/municipios")
async def get_municipios():
    return await _cached("municipios", 300, db.get_municipio_options)


@router.get("/hierarchy")
async def get_hierarchy(municipio: str = None):
    if municipio:
        return await _cached(f"hierarchy:{municipio}", 60, lambda: db.get_hierarchy(municipio))
    # Sin municipio: solo devuelve los que tienen alertas activas (mas rapido)
    return await _cached("hierarchy_alerts_only", 30, db.get_hierarchy_with_alerts)


@router.get("/hierarchy-all")
async def get_hierarchy_all():
    """Full hierarchy — all municipalities (slow, use only when needed)."""
    return await _cached("hierarchy", 60, db.get_hierarchy)


@router.get("/mesa/{mun}/{zona}/{puesto}/{mesa}")
async def get_mesa_detail(mun: str, zona: str, puesto: str, mesa: int):
    return await db.get_mesa_detail(mun, zona, puesto, mesa)


@router.get("/map")
async def get_map_data():
    return await _cached("map", 60, db.get_map_data)


@router.get("/pres-live")
async def get_pres_live():
    return await _cached("pres_live", 30, db.get_pres_live_projection)


@router.get("/coverage")
async def get_coverage(municipio: str = None):
    """Mesas esperadas (DIVIPOL) vs descargadas vs procesadas vs validadas por municipio."""
    return await _cached(
        f"coverage:{municipio or 'ALL'}",
        60,
        lambda: db.get_coverage_report(municipio),
    )


@router.post("/invalidate-cache")
async def invalidate_cache():
    """Force-clear all cached dashboard data and screenshot cache."""
    _cache.clear()
    # Also clear screenshot cache in manual_validate
    try:
        from backend.routers.manual_validate import _SCREENSHOT_CACHE
        _SCREENSHOT_CACHE.clear()
    except Exception:
        pass
    return {"status": "ok", "cleared": True}
