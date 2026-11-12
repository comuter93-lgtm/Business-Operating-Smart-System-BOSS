from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core import database as db_mod
from app.core.config import settings
from app.main import app


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "test_boss.db"
    storage_dir = tmp_path / "storage"
    backup_dir = tmp_path / "backups"
    db_url = f"sqlite:///{db_file}"

    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "boss_storage_dir", str(storage_dir))
    monkeypatch.setattr(settings, "boss_backup_dir", str(backup_dir))
    monkeypatch.setattr(settings, "login_max_attempts", 3)

    new_engine = db_mod._make_engine(db_url)
    new_session_local = db_mod.sessionmaker(bind=new_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", new_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", new_session_local)

    # Also update imported references in main
    import app.main as main_mod
    monkeypatch.setattr(main_mod, "SessionLocal", new_session_local)

    db_mod.init_db(new_engine)
    yield {"db_url": db_url, "db_file": db_file, "storage_dir": storage_dir, "backup_dir": backup_dir, "engine": new_engine, "SessionLocal": new_session_local}
    new_engine.dispose()


@pytest.fixture()
def client(isolated_env):
    with TestClient(app) as c:
        yield c

