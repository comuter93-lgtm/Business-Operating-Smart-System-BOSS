import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def _make_engine(url: str):
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}
    eng = create_engine(url, connect_args=connect_args, future=True, pool_pre_ping=True)

    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return eng


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine=None) -> None:
    eng = target_engine or engine
    # Import all models so Base.metadata registers every table before create_all
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=eng)


def create_sqlite_backup(db_url: str | None = None, backup_dir: Path | None = None) -> Path:
    """Create a consistent online backup for SQLite deployments (PostgreSQL uses pg_dump)."""
    url = db_url or settings.database_url
    if not url.startswith("sqlite:///"):
        raise NotImplementedError("Use pg_dump for PostgreSQL backup in production")
    src_path = Path(url.replace("sqlite:///", "", 1))
    if not src_path.exists():
        raise FileNotFoundError(f"Database file not found: {src_path}")
    dest_dir = backup_dir or settings.backup_path
    dest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_path = dest_dir / f"boss_backup_{ts}.db"

    src_conn = sqlite3.connect(str(src_path))
    dst_conn = sqlite3.connect(str(dest_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    return dest_path


def restore_sqlite_backup(backup_file: Path, target_db_url: str) -> None:
    """Restore a verified SQLite backup safely."""
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")
    if not target_db_url.startswith("sqlite:///"):
        raise NotImplementedError("Use pg_restore for PostgreSQL")
    dest_path = Path(target_db_url.replace("sqlite:///", "", 1))
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    # Verify backup integrity before overwriting target
    check_conn = sqlite3.connect(str(backup_file))
    try:
        res = check_conn.execute("PRAGMA integrity_check").fetchone()
        if not res or res[0] != "ok":
            raise ValueError(f"Backup integrity check failed: {res}")
    finally:
        check_conn.close()
    shutil.copy2(backup_file, dest_path)


def db_healthcheck(db: Session) -> bool:
    db.execute(text("SELECT 1"))
    return True

