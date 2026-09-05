from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, text

from mmex_recon.matcher import load_candidates, match_all
from mmex_recon.schemas import BankTransaction, MatchStatus
from mmex_web_api.recon_pipeline import commit_session
from tests.conftest import make_mmex_db
from tests.test_balances import _insert_account, _insert_txn


def test_fuzzy_auto_match(tmp_path) -> None:
    db = make_mmex_db(tmp_path / "data.mmb")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        conn.execute(
            text("INSERT INTO PAYEE_V1 (PAYEEID, PAYEENAME, CATEGID, ACTIVE) VALUES (1, 'Migros', -1, 1)")
        )
        _insert_txn(conn, 10, 1, "Withdrawal", "12.50", payee_id=1)
    start = date(2026, 1, 1)
    end = date(2026, 1, 2)
    mmex = load_candidates(engine, 1, start, end)
    assert len(mmex) == 1
    bank = [
        BankTransaction(date=date(2026, 1, 1), description="MIGROS GENEVE", amount=Decimal("-12.50"))
    ]
    matches = match_all(bank, mmex)
    assert matches[0].status == MatchStatus.AUTO_MATCHED
    assert matches[0].selected_trans_id == 10
    engine.dispose()


def test_commit_insert_and_reconcile(authed_client, mmex_settings) -> None:
    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        conn.execute(
            text("INSERT INTO PAYEE_V1 (PAYEEID, PAYEENAME, CATEGID, ACTIVE) VALUES (1, 'Coop', -1, 1)")
        )
        _insert_txn(conn, 11, 1, "Withdrawal", "5.00", payee_id=1)
    engine.dispose()

    session = {
        "account_id": 1,
        "matches": [
            {
                "bank_transaction": {
                    "date": "2026-01-01",
                    "description": "COOP",
                    "amount": "-5.00",
                },
                "status": "AUTO_MATCHED",
                "include": True,
                "selected_trans_id": 11,
                "selected_payee_name": "Coop",
                "candidates": [],
            },
            {
                "bank_transaction": {
                    "date": "2026-01-01",
                    "description": "New shop",
                    "amount": "-3.20",
                },
                "status": "NO_MATCH",
                "include": True,
                "selected_trans_id": None,
                "selected_payee_name": "New shop",
                "candidates": [],
            },
        ],
    }
    dry = commit_session(authed_client.app.state.mmex.engine, session, dry_run=True)
    assert dry["success"] is True
    assert dry["to_reconcile_count"] == 1
    assert dry["to_insert_count"] == 1
    live = commit_session(authed_client.app.state.mmex.engine, session, dry_run=False)
    assert live["success"] is True
    assert live["inserted"] == 1
    assert live["reconciled"] == 2


def test_patch_match_new_entry_fields(authed_client) -> None:
    sid = "sess1"
    authed_client.app.state.mmex.recon_sessions[sid] = {
        "id": sid,
        "account_id": 1,
        "matches": [
            {
                "include": True,
                "selected_trans_id": 11,
                "selected_payee_name": "Coop",
                "force_new_insert": False,
                "insert_as_transfer": False,
                "category_id": None,
                "candidates": [],
            }
        ],
    }
    resp = authed_client.patch(
        f"/api/recon/sessions/{sid}/matches/0",
        json={
            "selected_trans_id": None,
            "selected_payee_name": "New shop",
            "insert_as_transfer": True,
            "transfer_counterpart_account_id": 2,
            "transfer_counterpart_account_name": "Epargne",
            "force_trans_code": "Withdrawal",
            "category_id": 3,
            "category_name": "Food",
        },
    )
    assert resp.status_code == 200, resp.text
    row = resp.json()["matches"][0]
    assert row["selected_trans_id"] is None
    assert row["insert_as_transfer"] is True
    assert row["transfer_counterpart_account_name"] == "Epargne"
    assert row["selected_payee_name"] == "New shop"
    assert row["category_id"] == 3


def test_create_session_parse_error(authed_client, monkeypatch) -> None:
    from mmex_web_api import routes_recon

    def boom(*_args, **_kwargs):
        raise ValueError("Aucun parseur compatible")

    monkeypatch.setattr(routes_recon, "build_session", boom)
    resp = authed_client.post(
        "/api/recon/sessions",
        json={"paperless_id": 1, "account_id": 1},
    )
    assert resp.status_code == 422
