from __future__ import annotations

from fastapi.testclient import TestClient


def test_ledger_opens_without_login(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/info").status_code == 200
    assert client.get("/api/auth/status").status_code == 404
    assert client.get("/api/dashboard").status_code == 200
    assert client.get("/api/accounts").status_code == 200
    assert client.get("/api/schema").status_code == 200
