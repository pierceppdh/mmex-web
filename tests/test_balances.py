from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text

from mmex_domain.balances import account_rows
from mmex_domain.money import format_amount
from mmex_web_api.db import make_engine
from tests.conftest import make_mmex_db


def _insert_account(conn, account_id: int, name: str, acct_type: str, initial: str, currency_id: int = 1, favorite: str = "FALSE") -> None:
    conn.execute(
        text(
            """
            INSERT INTO ACCOUNTLIST_V1 (
                ACCOUNTID, ACCOUNTNAME, ACCOUNTTYPE, STATUS, FAVORITEACCT,
                INITIALBAL, CURRENCYID
            ) VALUES (:id, :name, :type, 'Open', :fav, :initial, :cur)
            """
        ),
        {
            "id": account_id,
            "name": name,
            "type": acct_type,
            "fav": favorite,
            "initial": initial,
            "cur": currency_id,
        },
    )


def _insert_txn(
    conn,
    trans_id: int,
    account_id: int,
    trans_code: str,
    amount: str,
    *,
    to_account_id: int = -1,
    to_amount: str | None = None,
    status: str = "",
    deleted: str = "",
    payee_id: int = -1,
    categ_id: int = -1,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO CHECKINGACCOUNT_V1 (
                TRANSID, ACCOUNTID, TOACCOUNTID, PAYEEID, TRANSCODE, TRANSAMOUNT,
                STATUS, CATEGID, TRANSDATE, DELETEDTIME, TOTRANSAMOUNT
            ) VALUES (
                :tid, :aid, :toid, :pid, :code, :amt, :status, :cid, '2026-01-01',
                :deleted, :toamt
            )
            """
        ),
        {
            "tid": trans_id,
            "aid": account_id,
            "toid": to_account_id,
            "pid": payee_id,
            "code": trans_code,
            "amt": amount,
            "status": status,
            "cid": categ_id,
            "deleted": deleted,
            "toamt": to_amount if to_amount is not None else amount,
        },
    )


def test_checking_flow_void_and_deleted(tmp_path: Path) -> None:
    db = make_mmex_db(tmp_path / "data.mmb")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "100")
        _insert_account(conn, 2, "Epargne", "Term", "0")
        _insert_txn(conn, 1, 1, "Deposit", "50")
        _insert_txn(conn, 2, 1, "Withdrawal", "20")
        _insert_txn(conn, 3, 1, "Withdrawal", "10", status="V")
        _insert_txn(conn, 4, 1, "Deposit", "5", deleted="2026-01-02T00:00:00")
        _insert_txn(conn, 5, 1, "Transfer", "15", to_account_id=2, to_amount="15")
    engine.dispose()

    payload = account_rows(make_engine(db))
    by_id = {a["account_id"]: a for a in payload["accounts"]}
    assert Decimal(by_id[1]["balance"]) == Decimal("115")  # 100+50-20-15
    assert Decimal(by_id[2]["balance"]) == Decimal("15")
    assert payload["upcoming_bills"] == 0


def test_reconciled_versus_actual_balance(tmp_path: Path) -> None:
    db = make_mmex_db(tmp_path / "data.mmb")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "Banque", "Checking", "100")
        _insert_txn(conn, 1, 1, "Deposit", "50")
        _insert_txn(conn, 2, 1, "Withdrawal", "20", status="R")
    engine.dispose()

    payload = account_rows(make_engine(db))
    acc = next(a for a in payload["accounts"] if a["account_id"] == 1)
    assert Decimal(acc["balance"]) == Decimal("130")
    assert Decimal(acc["reconciled_balance"]) == Decimal("80")
    assert Decimal(acc["difference"]) == Decimal("50")
    assert acc["reconciled_formatted"]
    assert acc["difference_formatted"]


def test_fx_transfer_uses_to_amount(tmp_path: Path) -> None:
    db = make_mmex_db(tmp_path / "data.mmb")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "EUR", "Checking", "0", 1)
        _insert_account(conn, 2, "USD", "Checking", "0", 2)
        _insert_txn(conn, 1, 1, "Transfer", "100", to_account_id=2, to_amount="110")
    engine.dispose()

    payload = account_rows(make_engine(db))
    by_id = {a["account_id"]: a for a in payload["accounts"]}
    assert Decimal(by_id[1]["balance"]) == Decimal("-100")
    assert Decimal(by_id[2]["balance"]) == Decimal("110")


def test_investment_uses_stock_market_value(tmp_path: Path) -> None:
    db = make_mmex_db(tmp_path / "data.mmb")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _insert_account(conn, 10, "PEA", "Investment", "0")
        conn.execute(
            text(
                """
                INSERT INTO STOCK_V1 (
                    STOCKID, HELDAT, PURCHASEDATE, STOCKNAME, SYMBOL,
                    NUMSHARES, PURCHASEPRICE, CURRENTPRICE, VALUE, COMMISSION
                ) VALUES (1, 10, '2020-01-01', 'Acme', 'ACM', 10, 5, 7.5, 75, 0)
                """
            )
        )
    engine.dispose()

    payload = account_rows(make_engine(db))
    pea = next(a for a in payload["accounts"] if a["account_id"] == 10)
    assert Decimal(pea["market_value"]) == Decimal("75")
    assert Decimal(pea["display_value"]) == Decimal("75")


def test_net_worth_skips_closed(tmp_path: Path) -> None:
    db = make_mmex_db(tmp_path / "data.mmb")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        _insert_account(conn, 1, "Ouvert", "Checking", "40", favorite="TRUE")
        conn.execute(
            text(
                """
                INSERT INTO ACCOUNTLIST_V1 (
                    ACCOUNTID, ACCOUNTNAME, ACCOUNTTYPE, STATUS, FAVORITEACCT,
                    INITIALBAL, CURRENCYID
                ) VALUES (2, 'Ferme', 'Checking', 'Closed', 'FALSE', 999, 1)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO BILLSDEPOSITS_V1 (
                    BDID, ACCOUNTID, PAYEEID, TRANSCODE, TRANSAMOUNT,
                    NEXTOCCURRENCEDATE
                ) VALUES (1, 1, -1, 'Withdrawal', 10, date('now'))
                """
            )
        )
    engine.dispose()

    payload = account_rows(make_engine(db))
    assert Decimal(payload["net_worth"]) == Decimal("40")
    assert len(payload["favorites"]) == 1
    assert payload["upcoming_bills"] == 1


def test_format_amount_groups() -> None:
    assert format_amount(Decimal("1234.5"), scale=100, pfx="", sfx=" €", decimal_point=",", group_separator=" ") == "1 234,50 €"
