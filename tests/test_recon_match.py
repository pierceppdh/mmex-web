from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from mmex_domain.money import format_cents
from mmex_domain.transactions import TransactionError
from mmex_recon.matcher import (
    load_candidates,
    match_all,
    match_transaction,
    supplement_foreign_amounts,
)
from mmex_recon.schemas import BankTransaction, MatchStatus, MmexTransaction
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


def test_amount_mismatch_still_lists_candidate() -> None:
    mmex = [
        MmexTransaction(
            trans_id=1,
            account_id=1,
            payee_name="NETFLIX.COM",
            trans_code="Withdrawal",
            amount=Decimal("-15.25"),
            status="",
            trans_date=date(2026, 5, 2),
        )
    ]
    bank = BankTransaction(
        date=date(2026, 5, 2),
        description="NETFLIX.COM subscription",
        amount=Decimal("-15.27"),
    )
    result = match_transaction(bank, mmex)
    assert result.status == MatchStatus.AMOUNT_MISMATCH
    assert result.candidates
    assert result.candidates[0].amount_match is False
    assert result.include is False


def test_date_window_drops_a_booking_outside_the_setting() -> None:
    mmex = [
        MmexTransaction(
            trans_id=1,
            account_id=1,
            payee_name="NETFLIX.COM",
            trans_code="Withdrawal",
            amount=Decimal("-15.25"),
            status="",
            trans_date=date(2026, 5, 2),
        )
    ]
    bank = BankTransaction(
        date=date(2026, 5, 8),
        description="NETFLIX.COM subscription",
        amount=Decimal("-15.25"),
    )
    narrow = match_transaction(bank, mmex)
    assert narrow.status == MatchStatus.NO_MATCH
    assert narrow.candidates == []
    wide = match_transaction(bank, mmex, tolerance_days=6)
    assert wide.status == MatchStatus.AUTO_MATCHED
    assert wide.selected_trans_id == 1


def test_amount_window_drops_a_near_gap_when_tightened() -> None:
    mmex = [
        MmexTransaction(
            trans_id=1,
            account_id=1,
            payee_name="NETFLIX.COM",
            trans_code="Withdrawal",
            amount=Decimal("-15.25"),
            status="",
            trans_date=date(2026, 5, 2),
        )
    ]
    bank = BankTransaction(
        date=date(2026, 5, 2),
        description="NETFLIX.COM subscription",
        amount=Decimal("-16.00"),
    )
    offered = match_transaction(bank, mmex)
    assert offered.status == MatchStatus.AMOUNT_MISMATCH
    assert offered.candidates
    assert offered.candidates[0].amount_match is False
    tight = match_transaction(bank, mmex, amount_delta=Decimal("0.50"))
    assert tight.status == MatchStatus.NO_MATCH
    assert tight.candidates == []
    exact = match_transaction(bank, mmex, amount_delta=Decimal("0"))
    assert exact.status == MatchStatus.NO_MATCH


def test_inbound_transfer_uses_to_amount_and_source_name(tmp_path) -> None:
    db = make_mmex_db(tmp_path / "data.mmb")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "Visa Cashback", "Credit Card", "0")
        _insert_account(conn, 2, "Postfinance", "Checking", "0")
        _insert_txn(
            conn,
            20,
            2,
            "Transfer",
            "7629.70",
            to_account_id=1,
            to_amount="7629.70",
        )
    mmex = load_candidates(engine, 1, date(2026, 1, 1), date(2026, 1, 1))
    assert len(mmex) == 1
    assert mmex[0].is_inbound_transfer is True
    assert mmex[0].amount == Decimal("7629.70")
    assert mmex[0].counterpart_account_name == "Postfinance"
    bank = BankTransaction(
        date=date(2026, 1, 1),
        description="PAIEMENT RECU",
        amount=Decimal("7629.70"),
    )
    result = match_transaction(bank, mmex, credit_card=True)
    assert result.status == MatchStatus.AUTO_MATCHED
    assert result.selected_trans_id == 20
    engine.dispose()


def test_hyphenated_merchant_matches_payee() -> None:
    mmex = [
        MmexTransaction(
            trans_id=70,
            account_id=1,
            payee_name="Coop",
            trans_code="Withdrawal",
            amount=Decimal("-6.95"),
            status="",
            trans_date=date(2026, 9, 18),
        )
    ]
    bank = BankTransaction(
        date=date(2026, 9, 18),
        description="ACHAT/SERVICE CARTE NO XXXX1332 COOP-4680 GLAND EIKENOTT GLAND (CH)",
        amount=Decimal("-6.95"),
    )
    result = match_transaction(bank, mmex)
    assert result.status == MatchStatus.AUTO_MATCHED
    assert result.selected_trans_id == 70


def test_cler_transfer_booked_on_another_account() -> None:
    transfer = MmexTransaction(
        trans_id=80,
        account_id=33,
        payee_name=None,
        trans_code="Transfer",
        amount=Decimal("-404.80"),
        status="",
        trans_date=date(2026, 9, 30),
        counterpart_account_name="Banque Cler - Zak",
        account_name="Postfinance Épargne Cécile et Pierre",
    )
    other = MmexTransaction(
        trans_id=81,
        account_id=3,
        payee_name="Swisslife",
        trans_code="Withdrawal",
        amount=Decimal("-404.80"),
        status="",
        trans_date=date(2026, 9, 30),
        account_name="Banque Cler - Zak",
    )
    bank = BankTransaction(
        date=date(2026, 9, 30),
        description=(
            "BANK CLER AG POSTFACH 4002 BASEL PIERROT MAURICE PRUD'HOMME "
            "CHEMIN DE L'AUBÉPINE 9B 1196 GLAND"
        ),
        amount=Decimal("-404.80"),
    )
    result = match_all(
        [bank],
        [transfer, other],
        statement_account_name="Postfinance Cécile et Pierre",
    )[0]
    assert result.status == MatchStatus.AUTO_MATCHED
    assert result.selected_trans_id == 80


def test_shared_amount_keeps_named_transfer_and_leaves_the_other() -> None:
    thomas = MmexTransaction(
        trans_id=90,
        account_id=1,
        payee_name=None,
        trans_code="Transfer",
        amount=Decimal("-10"),
        status="",
        trans_date=date(2026, 9, 7),
        counterpart_account_name="Yuh Thomas",
    )
    ludivine = MmexTransaction(
        trans_id=91,
        account_id=1,
        payee_name=None,
        trans_code="Transfer",
        amount=Decimal("-10"),
        status="",
        trans_date=date(2026, 9, 7),
        counterpart_account_name="Yuh Ludivine",
    )
    banks = [
        BankTransaction(
            date=date(2026, 9, 7),
            description="ACHAT/PRESTATION TWINT 07.09.2026 G'S CUISINE GILLY (CH)",
            amount=Decimal("-10"),
        ),
        BankTransaction(
            date=date(2026, 9, 7),
            description=(
                "ORDRE PERMANENT: 90- 33665595 SWISSQUOTE BANK SA "
                "THOMAS PRUD'HOMME 1196 GLAND"
            ),
            amount=Decimal("-10"),
        ),
    ]
    twint, standing = match_all(banks, [thomas, ludivine])
    assert standing.status == MatchStatus.AUTO_MATCHED
    assert standing.selected_trans_id == 90
    assert twint.selected_trans_id is None
    assert twint.status == MatchStatus.FUZZY_MATCHED


def test_reconciled_neighbour_is_not_reused() -> None:
    previous = MmexTransaction(
        trans_id=100,
        account_id=1,
        payee_name=None,
        trans_code="Transfer",
        amount=Decimal("-10"),
        status="R",
        trans_date=date(2026, 8, 31),
        counterpart_account_name="Yuh Ludivine",
    )
    bank = BankTransaction(
        date=date(2026, 9, 2),
        description="ACHAT/PRESTATION TWINT 02.09.2026 G'S CUISINE GILLY (CH)",
        amount=Decimal("-10"),
    )
    result = match_transaction(bank, [previous])
    assert result.status == MatchStatus.NO_MATCH
    assert result.selected_trans_id is None
    assert result.include is True
    assert result.candidates == []


def test_unique_amount_matches_when_the_payee_name_differs() -> None:
    mmex = [
        MmexTransaction(
            trans_id=110,
            account_id=1,
            payee_name="Link",
            trans_code="Withdrawal",
            amount=Decimal("-50"),
            status="",
            trans_date=date(2026, 9, 16),
        )
    ]
    bank = BankTransaction(
        date=date(2026, 9, 16),
        description="UBS SWITZERLAND AG RI REALIM SA CH. DE CHAMBÉSY 8 1292 CHAMBÉSY",
        amount=Decimal("-50"),
    )
    result = match_transaction(bank, mmex)
    assert result.status == MatchStatus.AUTO_MATCHED
    assert result.selected_trans_id == 110


def test_foreign_amount_load_finds_cler_transfer(tmp_path) -> None:
    db = make_mmex_db(tmp_path / "data.mmb")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "Postfinance Cécile et Pierre", "Checking", "0")
        _insert_account(conn, 2, "Postfinance Épargne Cécile et Pierre", "Checking", "0")
        _insert_account(conn, 3, "Banque Cler - Zak", "Checking", "0")
        _insert_txn(conn, 80, 2, "Transfer", "404.80", to_account_id=3, to_amount="404.80")
        _insert_txn(conn, 81, 3, "Withdrawal", "404.80")
    bank = [
        BankTransaction(
            date=date(2026, 1, 1),
            description="BANK CLER AG POSTFACH 4002 BASEL",
            amount=Decimal("-404.80"),
        )
    ]
    local = load_candidates(engine, 1, date(2026, 1, 1), date(2026, 1, 1))
    assert local == []
    merged = supplement_foreign_amounts(
        engine, 1, date(2026, 1, 1), date(2026, 1, 1), bank, local
    )
    engine.dispose()
    result = match_all(
        bank,
        merged,
        statement_account_name="Postfinance Cécile et Pierre",
    )[0]
    assert result.status == MatchStatus.AUTO_MATCHED
    assert result.selected_trans_id == 80
    booked = result.candidates[0].mmex_transaction
    assert booked.account_name == "Postfinance Épargne Cécile et Pierre"


def test_card_purchase_with_the_same_shop_stays_unmatched() -> None:
    card = MmexTransaction(
        trans_id=120,
        account_id=6,
        payee_name="Net viet",
        trans_code="Withdrawal",
        amount=Decimal("-15"),
        status="",
        trans_date=date(2026, 9, 1),
        account_name="Visa Cashback",
    )
    bank = BankTransaction(
        date=date(2026, 9, 1),
        description="ACHAT/PRESTATION TWINT 01.09.2026 NET VIET ORBE (CH)",
        amount=Decimal("-15"),
    )
    result = match_all(
        [bank],
        [card],
        statement_account_name="Postfinance Cécile et Pierre",
    )[0]
    assert result.status == MatchStatus.NO_MATCH
    assert result.selected_trans_id is None


def test_outbound_transfer_matches_counterpart_alias() -> None:
    mmex = [
        MmexTransaction(
            trans_id=32,
            account_id=32,
            payee_name=None,
            trans_code="Transfer",
            amount=Decimal("-7629.70"),
            status="",
            trans_date=date(2025, 12, 18),
            counterpart_account_name="Visa Cashback",
        )
    ]
    bank = BankTransaction(
        date=date(2025, 12, 18),
        description="PAIEMENT SWISSCARD AECS",
        amount=Decimal("-7629.70"),
    )
    result = match_transaction(bank, mmex)
    assert result.status == MatchStatus.AUTO_MATCHED
    assert result.selected_trans_id == 32


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
    engine = authed_client.app.state.mmex.engine
    dry = commit_session(engine, session, dry_run=True)
    assert dry["success"] is True
    assert dry["to_reconcile_count"] == 1
    assert dry["to_insert_count"] == 1
    assert dry["amounts_adjusted"] == 0
    live = commit_session(engine, session, dry_run=False)
    assert live["success"] is True
    assert live["inserted"] == 1
    assert live["reconciled"] == 2
    assert live["amounts_adjusted"] == 0
    assert "aligné" not in live["message"]
    booked = _booking(engine, 11)
    assert booked["amount"] == "5.00"
    assert booked["to_amount"] == "5.00"
    assert booked["status"] == "R"
    with engine.connect() as conn:
        created = conn.execute(
            text(
                "SELECT TRANSCODE, TRANSAMOUNT, STATUS FROM CHECKINGACCOUNT_V1 WHERE TRANSID != 11"
            )
        ).one()
    assert created[0] == "Withdrawal"
    assert format_cents(created[1]) == "3.20"
    assert created[2] == "R"


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


def _booking(engine, trans_id: int) -> dict[str, str]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT ACCOUNTID, TOACCOUNTID, TRANSCODE, TRANSAMOUNT, TOTRANSAMOUNT, STATUS
                  FROM CHECKINGACCOUNT_V1 WHERE TRANSID = :id
                """
            ),
            {"id": trans_id},
        ).one()
    return {
        "account_id": str(int(row[0])),
        "to_account_id": str(int(row[1])),
        "trans_code": row[2],
        "amount": format_cents(row[3]),
        "to_amount": format_cents(row[4]),
        "status": row[5] or "",
    }


def _splits(engine, trans_id: int) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT SPLITTRANSAMOUNT FROM SPLITTRANSACTIONS_V1
                 WHERE TRANSID = :id ORDER BY SPLITTRANSID
                """
            ),
            {"id": trans_id},
        ).fetchall()
    return [format_cents(row[0]) for row in rows]


def _link_session(trans_id: int, amount: str, *, account_id: int = 1) -> dict:
    return {
        "account_id": account_id,
        "matches": [
            {
                "bank_transaction": {
                    "date": "2026-01-01",
                    "description": "SHOP",
                    "amount": amount,
                },
                "status": "MANUAL",
                "include": True,
                "selected_trans_id": trans_id,
                "selected_payee_name": "Shop",
                "candidates": [],
            }
        ],
    }


def _lock(engine, account_id: int, statement_date: str = "2026-01-15") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE ACCOUNTLIST_V1
                   SET STATEMENTLOCKED = 1, STATEMENTDATE = :day
                 WHERE ACCOUNTID = :id
                """
            ),
            {"day": statement_date, "id": account_id},
        )


def test_reconcile_updates_withdrawal_to_bank_amount(authed_client) -> None:
    engine = authed_client.app.state.mmex.engine
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        conn.execute(
            text("INSERT INTO PAYEE_V1 (PAYEEID, PAYEENAME, CATEGID, ACTIVE) VALUES (1, 'Shop', -1, 1)")
        )
        _insert_txn(conn, 11, 1, "Withdrawal", "5.00", payee_id=1)
    session = _link_session(11, "-5.40")
    dry = commit_session(engine, session, dry_run=True)
    assert dry["amounts_adjusted"] == 1
    assert "1 montant(s) aligné(s) sur le relevé" in dry["message"]
    assert _booking(engine, 11)["amount"] == "5.00"
    assert _booking(engine, 11)["status"] == ""
    live = commit_session(engine, session, dry_run=False)
    assert live["success"] is True
    assert live["amounts_adjusted"] == 1
    assert live["adjusted_ids"] == [11]
    booked = _booking(engine, 11)
    assert booked["amount"] == "5.40"
    assert booked["to_amount"] == "5.40"
    assert booked["status"] == "R"
    assert booked["trans_code"] == "Withdrawal"


def test_reconcile_one_cent_delta_follows_the_statement(authed_client) -> None:
    engine = authed_client.app.state.mmex.engine
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        _insert_txn(conn, 11, 1, "Withdrawal", "5.00")
    commit_session(engine, _link_session(11, "-5.01"), dry_run=False)
    assert _booking(engine, 11)["amount"] == "5.01"
    assert _booking(engine, 11)["status"] == "R"


def test_reconcile_local_transfer_keeps_a_different_currency_leg(authed_client) -> None:
    engine = authed_client.app.state.mmex.engine
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        _insert_account(conn, 2, "Epargne", "Term", "0")
        _insert_txn(conn, 21, 1, "Transfer", "10.00", to_account_id=2, to_amount="10.00")
        _insert_txn(conn, 22, 1, "Transfer", "10.00", to_account_id=2, to_amount="9.00")
    commit_session(engine, _link_session(21, "-10.20"), dry_run=False)
    same = _booking(engine, 21)
    assert same["amount"] == "10.20"
    assert same["to_amount"] == "10.20"
    assert same["status"] == "R"
    assert same["account_id"] == "1"
    commit_session(engine, _link_session(22, "-10.20"), dry_run=False)
    fx = _booking(engine, 22)
    assert fx["amount"] == "10.20"
    assert fx["to_amount"] == "9.00"
    assert fx["trans_code"] == "Transfer"


def test_reconcile_inbound_transfer_updates_the_destination_amount(authed_client) -> None:
    engine = authed_client.app.state.mmex.engine
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        _insert_account(conn, 2, "Epargne", "Term", "0")
        _insert_txn(conn, 31, 2, "Transfer", "10.00", to_account_id=1, to_amount="10.00")
        _insert_txn(conn, 32, 2, "Transfer", "10.00", to_account_id=1, to_amount="9.00")
    commit_session(engine, _link_session(31, "10.15"), dry_run=False)
    same = _booking(engine, 31)
    assert same["amount"] == "10.15"
    assert same["to_amount"] == "10.15"
    assert same["account_id"] == "2"
    assert same["to_account_id"] == "1"
    commit_session(engine, _link_session(32, "9.40"), dry_run=False)
    fx = _booking(engine, 32)
    assert fx["amount"] == "10.00"
    assert fx["to_amount"] == "9.40"


def test_reconcile_foreign_booking_stays_on_its_account(authed_client) -> None:
    engine = authed_client.app.state.mmex.engine
    with engine.begin() as conn:
        _insert_account(conn, 1, "Courant", "Checking", "0")
        _insert_account(conn, 2, "Epargne", "Term", "0")
        _insert_txn(conn, 41, 2, "Withdrawal", "5.00")
    commit_session(engine, _link_session(41, "-5.40", account_id=1), dry_run=False)
    booked = _booking(engine, 41)
    assert booked["account_id"] == "2"
    assert booked["amount"] == "5.40"
    assert booked["to_amount"] == "5.40"
    assert booked["status"] == "R"


def test_reconcile_rescales_splits_with_the_parent_amount(authed_client) -> None:
    engine = authed_client.app.state.mmex.engine
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        _insert_txn(conn, 51, 1, "Withdrawal", "4.00")
        conn.execute(
            text(
                """
                INSERT INTO SPLITTRANSACTIONS_V1
                    (SPLITTRANSID, TRANSID, CATEGID, SPLITTRANSAMOUNT, NOTES)
                VALUES
                    (1, 51, -1, '1.00', ''),
                    (2, 51, -1, '3.00', '')
                """
            )
        )
    commit_session(engine, _link_session(51, "-5.00"), dry_run=False)
    assert _booking(engine, 51)["amount"] == "5.00"
    assert _splits(engine, 51) == ["1.25", "3.75"]


def test_reconcile_split_rounding_lands_on_the_last_line(authed_client) -> None:
    engine = authed_client.app.state.mmex.engine
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        _insert_txn(conn, 52, 1, "Withdrawal", "10.00")
        conn.execute(
            text(
                """
                INSERT INTO SPLITTRANSACTIONS_V1
                    (SPLITTRANSID, TRANSID, CATEGID, SPLITTRANSAMOUNT, NOTES)
                VALUES
                    (3, 52, -1, '1.00', ''),
                    (4, 52, -1, '9.00', '')
                """
            )
        )
    commit_session(engine, _link_session(52, "-10.03"), dry_run=False)
    assert _booking(engine, 52)["amount"] == "10.03"
    assert _splits(engine, 52) == ["1.00", "9.03"]


def test_reconcile_rejects_a_split_that_would_not_stay_positive(authed_client) -> None:
    engine = authed_client.app.state.mmex.engine
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        _insert_txn(conn, 53, 1, "Withdrawal", "4.00")
        conn.execute(
            text(
                """
                INSERT INTO SPLITTRANSACTIONS_V1
                    (SPLITTRANSID, TRANSID, CATEGID, SPLITTRANSAMOUNT, NOTES)
                VALUES
                    (5, 53, -1, '5.00', ''),
                    (6, 53, -1, '-1.00', '')
                """
            )
        )
    with pytest.raises(TransactionError, match="split amount must stay positive"):
        commit_session(engine, _link_session(53, "-5.00"), dry_run=False)
    assert _booking(engine, 53)["amount"] == "4.00"
    assert _booking(engine, 53)["status"] == ""
    assert _splits(engine, 53) == ["5.00", "-1.00"]


def test_reconcile_amount_change_respects_the_statement_lock(authed_client) -> None:
    engine = authed_client.app.state.mmex.engine
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        _insert_account(conn, 2, "Epargne", "Term", "0")
        _insert_txn(conn, 61, 1, "Withdrawal", "5.00")
        _insert_txn(conn, 62, 1, "Withdrawal", "5.00")
        _insert_txn(conn, 63, 1, "Transfer", "10.00", to_account_id=2, to_amount="10.00")
    _lock(engine, 1)
    session = _link_session(61, "-5.40")
    sid = "lock-amount"
    authed_client.app.state.mmex.recon_sessions[sid] = session
    dry = authed_client.post(f"/api/recon/sessions/{sid}/commit", json={"dry_run": True})
    assert dry.status_code == 423, dry.text
    live = authed_client.post(f"/api/recon/sessions/{sid}/commit", json={"dry_run": False})
    assert live.status_code == 423, live.text
    assert "statement locked" in live.json()["detail"]
    blocked = _booking(engine, 61)
    assert blocked["amount"] == "5.00"
    assert blocked["status"] == ""

    commit_session(engine, _link_session(62, "-5.00"), dry_run=False)
    same = _booking(engine, 62)
    assert same["amount"] == "5.00"
    assert same["status"] == "R"

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE ACCOUNTLIST_V1 SET STATEMENTLOCKED = 0 WHERE ACCOUNTID = 1")
        )
    _lock(engine, 2)
    with pytest.raises(TransactionError, match="statement locked"):
        commit_session(engine, _link_session(63, "-10.20"), dry_run=False)
    assert _booking(engine, 63)["amount"] == "10.00"
    assert _booking(engine, 63)["status"] == ""


def test_reconcile_inbound_amount_change_leaves_splits_on_the_source_amount(authed_client) -> None:
    engine = authed_client.app.state.mmex.engine
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "0")
        _insert_account(conn, 2, "Epargne", "Term", "0")
        _insert_txn(conn, 71, 2, "Transfer", "10.00", to_account_id=1, to_amount="9.00")
        conn.execute(
            text(
                """
                INSERT INTO SPLITTRANSACTIONS_V1
                    (SPLITTRANSID, TRANSID, CATEGID, SPLITTRANSAMOUNT, NOTES)
                VALUES (7, 71, -1, '10.00', '')
                """
            )
        )
    commit_session(engine, _link_session(71, "9.40"), dry_run=False)
    booked = _booking(engine, 71)
    assert booked["amount"] == "10.00"
    assert booked["to_amount"] == "9.40"
    assert _splits(engine, 71) == ["10.00"]


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
