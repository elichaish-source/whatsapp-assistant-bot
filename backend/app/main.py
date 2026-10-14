import logging

from fastapi import FastAPI

from .routers import auth, clients, lookups, projects, tasks

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="עוזר אישי", docs_url="/api/docs", openapi_url="/api/openapi.json")

for module in (auth, lookups, clients, projects, tasks):
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
