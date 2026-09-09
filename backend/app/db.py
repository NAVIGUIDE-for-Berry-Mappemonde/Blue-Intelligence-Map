"""app.db — Client MongoDB (Motor) et accès aux réglages persistés."""
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME, DEFAULT_SETTINGS, MONGO_URL

# Timeouts explicites : sans socketTimeoutMS un upsert Atlas peut rester
# bloqué indéfiniment et geler le dump mondial (event loop uvicorn unique).
# 300 s (et non 60 s) : le débit Atlas M0 est throttlé — lire les ~32k
# marinas live prend ~150 s, un batch peut dépasser 60 s.
client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=20_000,
    connectTimeoutMS=20_000,
    socketTimeoutMS=300_000,
    maxPoolSize=20,
    retryWrites=True,
)
db = client[DB_NAME]


async def get_settings() -> dict:
    doc = await db.settings.find_one({"_id": "global"})
    return {**DEFAULT_SETTINGS, **(doc or {})}
