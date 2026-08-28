"""app.db — Client MongoDB (Motor) et accès aux réglages persistés."""
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME, DEFAULT_SETTINGS, MONGO_URL

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


async def get_settings() -> dict:
    doc = await db.settings.find_one({"_id": "global"})
    return {**DEFAULT_SETTINGS, **(doc or {})}
