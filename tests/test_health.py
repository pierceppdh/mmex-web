from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mmex_web_api.config import Settings
from mmex_web_api.main import create_app
from tests.conftest import make_mmex_db


def _settings(tmp_path: Path, with_db: bool = True) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    db_path = data / "data.mmb"
    if with_db:
        make_mmex_db(db_path, user_version=21)
    return Settings(
        mmex_data_dir=data,
        mmex_db_path=db_path,
        enable_openapi=False,
        secret_key="unit-test-secret-key-not-for-production",
        auth_username="mmex",
        auth_password="secret",
    )


def test_health_ok_with_fixture_db(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, with_db=True))
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.15.0"
    assert body["paperless"]["configured"] is False
    assert body["db"]["exists"] is True
    assert body["db"]["info_table"]["DATAVERSION"] == "3"
    assert body["schema"]["ok"] is True
    assert body["lock"]["acquired"] is True
    assert body["lock"]["read_only"] is False
    assert body["last_backup"] is not None


def test_health_degraded_without_db(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, with_db=False))
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"]["exists"] is False
    assert body["last_backup"] is None
