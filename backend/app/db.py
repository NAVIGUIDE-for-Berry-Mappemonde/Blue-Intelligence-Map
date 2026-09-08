"""app.db — Client MongoDB (Motor) et accès aux réglages persistés."""
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME, DEFAULT_SETTINGS, MONGO_URL

# Timeouts explicites : sans socketTimeoutMS un upsert Atlas peut rester
# bloqué indéfiniment et geler le dump mondial (event loop uvicorn unique).
client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=20_000,
    connectTimeoutMS=20_000,
    socketTimeoutMS=60_000,
    maxPoolSize=20,
    retryWrites=True,
)
db = client[DB_NAME]


async def get_settings() -> dict:
    doc = await db.settings.find_one({"_id": "global"})
    return {**DEFAULT_SETTINGS, **(doc or {})}
