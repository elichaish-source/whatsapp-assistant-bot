import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .bot.reminders import reminder_loop
from .config import get_settings
from .routers import auth, bot, clients, lookups, projects, tasks

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # לולאת התזכורות עולה רק כשהבוט מוגדר. נפילה שלה לא מפילה את הדשבורד
    task: asyncio.Task | None = None
    if get_settings().waha_webhook_hmac_key:
        task = asyncio.create_task(reminder_loop())
    else:
        log.info("הבוט בוואטסאפ כבוי (אין WAHA_WEBHOOK_HMAC_KEY), לולאת התזכורות לא עלתה")
    try:
        yield
    finally:
        if task:
            task.cancel()


app = FastAPI(
    title="עוזר אישי",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

for module in (auth, lookups, clients, projects, tasks, bot):
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
