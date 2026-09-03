from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mmex_web_api.config import Settings
from mmex_web_api.main import create_app
from tests.conftest import login, make_mmex_db


def test_health_and_status_are_public(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    status = client.get("/api/auth/status")
    assert status.status_code == 200
    body = status.json()
    assert body["authenticated"] is False
    assert body["bootstrap"] is False


def test_ledger_requires_login(client: TestClient) -> None:
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/accounts").status_code == 401
    assert client.get("/api/schema").status_code == 401


def test_login_logout_roundtrip(client: TestClient) -> None:
    bad = client.post("/api/auth/login", json={"username": "mmex", "password": "nope"})
    assert bad.status_code == 401
    login(client)
    me = client.get("/api/auth/status").json()
    assert me["authenticated"] is True
    assert me["username"] == "mmex"
    assert client.get("/api/dashboard").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/auth/status").json()["authenticated"] is False
    assert client.get("/api/dashboard").status_code == 401


def test_bootstrap_creates_file_and_session(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    db = make_mmex_db(data / "data.mmb")
    settings = Settings(
        mmex_data_dir=data,
        mmex_db_path=db,
        secret_key="unit-test-secret-key-not-for-production",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        status = client.get("/api/auth/status").json()
        assert status["bootstrap"] is True
        short = client.post(
            "/api/auth/bootstrap", json={"username": "pierre", "password": "short"}
        )
        assert short.status_code == 400
        ok = client.post(
            "/api/auth/bootstrap",
            json={"username": "pierre", "password": "long-enough"},
        )
        assert ok.status_code == 200
        assert (data / "auth.json").is_file()
        assert client.get("/api/auth/status").json()["authenticated"] is True
        again = client.post(
            "/api/auth/bootstrap",
            json={"username": "other", "password": "long-enough"},
        )
        assert again.status_code == 409
        client.post("/api/auth/logout")
        login(client, "pierre", "long-enough")
        assert client.get("/api/dashboard").status_code == 200
