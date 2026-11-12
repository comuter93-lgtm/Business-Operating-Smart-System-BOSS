from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.api import auth, finance, inventory, operations, permissions
from app.core.config import settings
from app.core.database import SessionLocal, db_healthcheck, get_db, init_db
from app.core.logging import get_logger
from app.workers.automation import seed_default_automation_rules

logger = get_logger("boss.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_default_automation_rules(db)
    finally:
        db.close()
    logger.info("BOSS backend initialized")
    yield


app = FastAPI(
    title=settings.boss_app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.boss_env != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(permissions.router)
app.include_router(inventory.router)
app.include_router(operations.router)
app.include_router(finance.router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db_healthcheck(db)
    return {"status": "ok", "app": settings.boss_app_name, "saas_multi_tenancy": False}

