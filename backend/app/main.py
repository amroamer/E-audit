from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .api.routes import router

app = FastAPI(title="ZATCA VAT Audit Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def _startup() -> None:
    # Demo bootstrap: ensure schemas/tables exist. Seed with `python -m app.seed.seed`.
    init_db()


@app.get("/")
def root():
    return {"service": "ZATCA VAT Audit Agent", "docs": "/docs", "api": "/api/health"}
