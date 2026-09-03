from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from mmex_web_api.config import Settings
from mmex_web_api.lock import PROTOCOL, WriterLock, exclusive_write, peek_lock
from tests.test_transactions import _seed


def test_lock_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "data.mmb.lock"
    a = WriterLock(path, "mmex-web")
    b = WriterLock(path, "bank-reconciliation-app")
    assert a.acquire() is True
    assert a.acquired is True
    meta = peek_lock(path)
    assert meta["protocol"] == PROTOCOL
    assert meta["holder"] == "mmex-web"
    assert b.acquire() is False
    assert b.read_only is True
    status = b.status()
    assert status["holder"] == "mmex-web"
    a.release()
    released = peek_lock(path)
    assert released.get("holder") is None
    assert b.acquire() is True
    b.release()


def test_exclusive_write_context(tmp_path: Path) -> None:
    path = tmp_path / "data.mmb.lock"
    with exclusive_write(path, "bank-reconciliation-app") as lock:
        assert lock.acquired is True
        other = WriterLock(path, "mmex-web")
        assert other.acquire() is False
    assert peek_lock(path).get("holder") is None
    assert WriterLock(path, "mmex-web").acquire() is True


def test_yield_and_retake_lock(authed_client: TestClient, mmex_settings: Settings) -> None:
    _seed(mmex_settings)
    health = authed_client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["lock"]["acquired"] is True
    assert health.json()["lock"]["holder"] == "mmex-web"

    released = authed_client.post("/api/lock/release")
    assert released.status_code == 200, released.text
    body = released.json()
    assert body["acquired"] is False
    assert body["read_only"] is True
    assert body["holder"] is None

    blocked = authed_client.put(
        "/api/settings",
        json={"username": "should-not-write"},
    )
    assert blocked.status_code == 423

    sidecar = Path(str(mmex_settings.db_path) + ".lock")
    recon = WriterLock(sidecar, "bank-reconciliation-app")
    assert recon.acquire() is True

    taken = authed_client.post("/api/lock/acquire")
    assert taken.status_code == 409
    assert "bank-reconciliation-app" in taken.json()["detail"]

    recon.release()
    ok = authed_client.post("/api/lock/acquire")
    assert ok.status_code == 200, ok.text
    assert ok.json()["acquired"] is True
    assert ok.json()["holder"] == "mmex-web"

    saved = authed_client.put("/api/settings", json={"username": ""})
    assert saved.status_code == 200, saved.text


def test_lock_json_is_mmex_lock_v1(tmp_path: Path) -> None:
    path = tmp_path / "data.mmb.lock"
    lock = WriterLock(path, "mmex-web")
    assert lock.acquire()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["protocol"] == "mmex-lock-v1"
    assert data["holder"] == "mmex-web"
    assert "pid" in data
    assert "acquired_at" in data
    lock.release()
