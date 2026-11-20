"""Reconciliation sessions survive a process restart."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from mmex_web_api.session_store import SessionStore


def test_store_reloads_an_open_session(tmp_path) -> None:
    path = tmp_path / "recon-sessions.json"
    store = SessionStore(path)
    store["abc"] = {
        "id": "abc",
        "paperless_doc_id": 9,
        "committed": False,
        "matches": [{"include": True}],
    }
    store["old"] = {
        "id": "old",
        "paperless_doc_id": 9,
        "committed": True,
        "matches": [],
    }
    reloaded = SessionStore(path)
    assert reloaded.get("abc")["matches"][0]["include"] is True
    assert reloaded.latest_open(9)["id"] == "abc"
    assert reloaded.latest_open(3) is None


def test_patch_survives_a_new_process(authed_client: TestClient, mmex_settings) -> None:
    sid = "kept"
    authed_client.app.state.mmex.recon_sessions[sid] = {
        "id": sid,
        "paperless_doc_id": 12,
        "committed": False,
        "matches": [{"include": True, "selected_trans_id": 1, "candidates": []}],
    }
    patched = authed_client.patch(
        f"/api/recon/sessions/{sid}/matches/0",
        json={"selected_payee_name": "Migros"},
    )
    assert patched.status_code == 200, patched.text

    reloaded = SessionStore(mmex_settings.mmex_data_dir / "recon-sessions.json")
    again = reloaded.latest_open(12)
    assert again is not None
    assert again["matches"][0]["selected_payee_name"] == "Migros"


def test_committed_session_is_not_resumed(tmp_path) -> None:
    path = tmp_path / "recon-sessions.json"
    store = SessionStore(path)
    store["done"] = {"id": "done", "paperless_doc_id": 4, "committed": True, "matches": []}
    assert SessionStore(path).latest_open(4) is None


def test_stale_committed_session_is_dropped(tmp_path) -> None:
    path = tmp_path / "recon-sessions.json"
    store = SessionStore(path)
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="seconds")
    store["done"] = {
        "id": "done",
        "paperless_doc_id": 4,
        "committed": True,
        "matches": [],
        "updated_at": old,
    }
    # The setter stamps now. Force the stale stamp and reload.
    store._items["done"]["updated_at"] = old
    store._write()
    assert SessionStore(path).get("done") is None
