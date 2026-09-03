from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def test_color_followup_and_attachment_file(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)

    bad = authed_client.post(
        "/api/transactions",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "2",
            "trans_date": "2026-04-01",
            "payee_id": 10,
            "color": 99,
        },
    )
    assert bad.status_code == 400

    created = authed_client.post(
        "/api/transactions",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "2.50",
            "trans_date": "2026-04-01",
            "payee_id": 10,
            "categ_id": 2,
            "color": 3,
            "followup_id": 1,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    tid = body["trans_id"]
    assert body["color"] == 3
    assert body["followup_id"] == 1
    assert body["attachments"] == []

    missing = authed_client.post(
        f"/api/transactions/{tid}/attachments",
        files={"file": ("note.txt", b"", "text/plain")},
    )
    assert missing.status_code == 400

    uploaded = authed_client.post(
        f"/api/transactions/{tid}/attachments",
        files={"file": ("reçu 1.txt", b"hello-mmex", "text/plain")},
        data={"description": "ticket"},
    )
    assert uploaded.status_code == 200, uploaded.text
    att = uploaded.json()
    assert att["ref_type"] == "Transaction"
    assert att["ref_id"] == tid
    assert att["description"] == "ticket"
    assert "re" in att["filename"].lower() or "1.txt" in att["filename"]
    aid = att["attachment_id"]

    disk = mmex_settings.attachments_dir / att["filename"]
    assert disk.is_file()
    assert disk.read_bytes() == b"hello-mmex"

    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT REFTYPE, REFID, DESCRIPTION, FILENAME "
                "FROM ATTACHMENT_V1 WHERE ATTACHMENTID = :id"
            ),
            {"id": aid},
        ).fetchone()
        assert row[0] == "Transaction"
        assert int(row[1]) == tid
        assert row[2] == "ticket"
        assert row[3] == att["filename"]
        color_row = conn.execute(
            text("SELECT COLOR, FOLLOWUPID FROM CHECKINGACCOUNT_V1 WHERE TRANSID = :id"),
            {"id": tid},
        ).fetchone()
        assert int(color_row[0]) == 3
        assert int(color_row[1]) == 1
    engine.dispose()

    listed = authed_client.get(f"/api/accounts/1/transactions").json()["transactions"]
    row0 = next(t for t in listed if t["trans_id"] == tid)
    assert row0["attachment_count"] == 1
    assert row0["color"] == 3
    assert row0["followup_id"] == 1

    download = authed_client.get(f"/api/attachments/{aid}/file")
    assert download.status_code == 200
    assert download.content == b"hello-mmex"

    deleted = authed_client.delete(f"/api/attachments/{aid}")
    assert deleted.status_code == 200
    assert not disk.exists()
    gone = authed_client.get(f"/api/transactions/{tid}").json()
    assert gone["attachments"] == []
    assert gone["attachment_count"] == 0

    unknown_txn = authed_client.post(
        "/api/transactions/999999/attachments",
        files={"file": ("x.txt", b"x", "text/plain")},
    )
    assert unknown_txn.status_code == 404
