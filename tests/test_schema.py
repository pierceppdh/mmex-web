from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_domain.models import Base
from mmex_domain.version import MAX_USER_VERSION, MIN_USER_VERSION, read_schema_status
from mmex_web_api.config import Settings
from mmex_web_api.db import make_engine
from mmex_web_api.main import create_app
from tests.conftest import make_mmex_db


def test_schema_ok(authed_client: TestClient) -> None:
    resp = authed_client.get("/api/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["user_version"] == 21
    assert body["info"]["BASECURRENCYID"] == "1"


def test_refuse_old_version(tmp_path: Path) -> None:
    db = make_mmex_db(tmp_path / "old.mmb", user_version=12)
    engine = make_engine(db)
    status = read_schema_status(engine)
    assert status.ok is False
    assert status.user_version == 12
    assert str(MIN_USER_VERSION) in (status.error or "")


def test_refuse_future_version(tmp_path: Path) -> None:
    db = make_mmex_db(tmp_path / "new.mmb", user_version=MAX_USER_VERSION + 5)
    engine = make_engine(db)
    status = read_schema_status(engine)
    assert status.ok is False
    assert status.user_version == MAX_USER_VERSION + 5


def test_missing_tables(tmp_path: Path) -> None:
    path = tmp_path / "empty.mmb"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text("PRAGMA user_version = 21"))
        conn.execute(
            text(
                "CREATE TABLE INFOTABLE_V1 (INFOID integer primary key, "
                "INFONAME TEXT, INFOVALUE TEXT)"
            )
        )
    status = read_schema_status(engine)
    assert status.ok is False
    assert "ACCOUNTLIST_V1" in status.missing_tables


def test_dashboard_conflict_on_bad_schema(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    db = data / "data.mmb"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA user_version = 3"))
    engine.dispose()
    settings = Settings(
        mmex_data_dir=data,
        mmex_db_path=db,
        secret_key="unit-test-secret-key-not-for-production",
        auth_username="mmex",
        auth_password="secret",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "mmex", "password": "secret"})
        resp = client.get("/api/dashboard")
    assert resp.status_code == 409
