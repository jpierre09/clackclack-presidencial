"""Dashboard API endpoints."""
from fastapi import APIRouter
from backend import database as db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_summary():
    return await db.get_dashboard_summary()


@router.get("/hierarchy")
async def get_hierarchy(municipio: str = None):
    data = await db.get_hierarchy()
    if municipio:
        data = [m for m in data if m["municipio_cod"] == municipio]
    return data


@router.get("/mesa/{mun}/{zona}/{puesto}/{mesa}")
async def get_mesa_detail(mun: str, zona: str, puesto: str, mesa: int):
    return await db.get_mesa_detail(mun, zona, puesto, mesa)


@router.get("/map")
async def get_map_data():
    return await db.get_map_data()


@router.get("/camara-live")
async def get_camara_live():
    return await db.get_camara_live_projection()
