"""Global settings endpoints."""
from fastapi import APIRouter

from backend import database as db
from backend.models import UserSettings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/user")
async def get_user_settings():
    return {
        "user_name": await db.get_setting("user_name", ""),
        "user_cc": await db.get_setting("user_cc", ""),
    }


@router.put("/user")
async def set_user_settings(payload: UserSettings):
    await db.set_setting("user_name", payload.user_name or "")
    await db.set_setting("user_cc", payload.user_cc or "")
    return {"status": "ok"}
