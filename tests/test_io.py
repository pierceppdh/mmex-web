from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def _make_txn(client: TestClient, account_id: int, **kwargs) -> int:
    body = {
        "account_id": account_id,
        "trans_code": "Withdrawal",
        "trans_amount": "12.50",
        "trans_date": "2026-03-01",
        "payee_id": 10,
        "categ_id": 2,
        "status": "",
        "notes": "io-test",
        "tag_ids": [1],
        **kwargs,
    }
    resp = client.post("/api/transactions", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["trans_id"]


def test_csv_qif_xml_roundtrip_and_dry_run(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    _make_txn(authed_client, 1)
    _make_txn(
        authed_client,
        1,
        trans_code="Deposit",
        trans_amount="8.00",
        trans_date="2026-03-02",
        notes="io-in",
    )

    meta = authed_client.get("/api/io/meta")
    assert meta.status_code == 200
    assert "csv" in meta.json()["formats"]
    assert "date" in meta.json()["mmex_format"]

    csv_file = authed_client.get("/api/io/export", params={"account_id": 1, "fmt": "csv"})
    assert csv_file.status_code == 200, csv_file.text
    csv_bytes = csv_file.content
    assert b"Date" in csv_bytes or b"date" in csv_bytes
    assert b"12.50" in csv_bytes or b"-12.50" in csv_bytes

    preview = authed_client.post(
        "/api/io/preview",
        data={
            "account_id": 2,
            "fmt": "csv",
            "skip_first": 1,
            "amount_sign": "deposit",
        },
        files={"file": ("a.csv", csv_bytes, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["dry_run"] is True
    assert preview.json()["imported"] == 0
    assert preview.json()["preview"]

    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT COUNT(*) FROM CHECKINGACCOUNT_V1 WHERE ACCOUNTID = 2")
        ).scalar()
    engine.dispose()

    imported = authed_client.post(
        "/api/io/import",
        data={
            "account_id": 2,
            "fmt": "csv",
            "skip_first": 1,
            "amount_sign": "deposit",
        },
        files={"file": ("a.csv", csv_bytes, "text/csv")},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 2
    assert imported.json()["errors"] == []

    listed = authed_client.get("/api/accounts/2/transactions")
    rows = listed.json()["transactions"]
    assert len(rows) == 2
    amounts = {Decimal(r["trans_amount"]) for r in rows}
    assert Decimal("12.5") in amounts
    assert Decimal("8") in amounts
    codes = {r["trans_code"] for r in rows}
    assert "Withdrawal" in codes
    assert "Deposit" in codes

    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        after_preview_account = conn.execute(
            text("SELECT COUNT(*) FROM CHECKINGACCOUNT_V1 WHERE ACCOUNTID = 2")
        ).scalar()
    engine.dispose()
    assert after_preview_account == (before or 0) + 2

    qif = authed_client.get("/api/io/export", params={"account_id": 1, "fmt": "qif"})
    assert qif.status_code == 200
    assert qif.content.startswith(b"!Type:Bank")
    qif_imp = authed_client.post(
        "/api/io/import",
        data={"account_id": 2, "fmt": "qif", "date_format": "YYYY-MM-DD"},
        files={"file": ("a.qif", qif.content, "application/x-qif")},
    )
    assert qif_imp.status_code == 200, qif_imp.text
    assert qif_imp.json()["imported"] == 2

    xml = authed_client.get("/api/io/export", params={"account_id": 1, "fmt": "xml"})
    assert xml.status_code == 200
    assert b"Workbook" in xml.content
    xml_prev = authed_client.post(
        "/api/io/preview",
        data={"account_id": 2, "fmt": "xml", "skip_first": 1, "amount_sign": "deposit"},
        files={"file": ("a.xml", xml.content, "application/xml")},
    )
    assert xml_prev.status_code == 200, xml_prev.text
    assert xml_prev.json()["imported"] == 0
    assert any(p.get("parsed") for p in xml_prev.json()["preview"])

    tiny = b"date,payee,amount\nnot-a-date,X,10\n"
    bad = authed_client.post(
        "/api/io/import",
        data={
            "account_id": 2,
            "fmt": "csv",
            "fields": "date,payee,amount",
            "skip_first": 0,
        },
        files={"file": ("bad.csv", tiny, "text/csv")},
    )
    assert bad.status_code == 200
    assert bad.json()["imported"] == 0
    assert bad.json()["errors"]

    for row in authed_client.get("/api/accounts/2/transactions").json()["transactions"]:
        authed_client.post(f"/api/transactions/{row['trans_id']}/delete")
