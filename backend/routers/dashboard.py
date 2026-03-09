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


@router.get("/hierarchy")
async def get_hierarchy(municipio: str = None):
    data = await _cached("hierarchy", 60, db.get_hierarchy)
    if municipio:
        data = [m for m in data if m["municipio_cod"] == municipio]
    return data


@router.get("/mesa/{mun}/{zona}/{puesto}/{mesa}")
async def get_mesa_detail(mun: str, zona: str, puesto: str, mesa: int):
    return await db.get_mesa_detail(mun, zona, puesto, mesa)


@router.get("/map")
async def get_map_data():
    return await _cached("map", 60, db.get_map_data)


@router.get("/camara-live")
async def get_camara_live():
    return await _cached("camara_live", 30, db.get_camara_live_projection)


@router.post("/invalidate-cache")
async def invalidate_cache():
    """Force-clear all cached dashboard data."""
    _cache.clear()
    return {"status": "ok", "cleared": True}
