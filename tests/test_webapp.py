from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def _write_sidecar(path, rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE New_Transaction (
            ID INTEGER PRIMARY KEY,
            Date TEXT, Account TEXT, ToAccount TEXT, Status TEXT, Type TEXT,
            Payee TEXT, Category TEXT, SubCategory TEXT, Amount NUMERIC, Notes TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO New_Transaction VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()


def test_webapp_sidecar_dry_run_then_import(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    sidecar = mmex_settings.mmex_data_dir / "MMEX_New_Transaction.db"
    _write_sidecar(
        sidecar,
        [
            (
                1,
                "2026-08-02",
                "Courant",
                "None",
                "",
                "Withdrawal",
                "Boulanger",
                "Food",
                "Groceries",
                4.20,
                "webapp",
            ),
            (
                2,
                "2026-08-03",
                "MissingAcct",
                "None",
                "",
                "Withdrawal",
                "Boulanger",
                "Food",
                "",
                1,
                "",
            ),
        ],
    )

    status = authed_client.get("/api/webapp")
    assert status.status_code == 200, status.text
    assert status.json()["exists"] is True
    assert status.json()["pending"] == 2

    preview = authed_client.post("/api/webapp/import", json={"dry_run": True})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["dry_run"] is True
    assert body["imported"] == 1
    assert len(body["errors"]) == 1

    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM CHECKINGACCOUNT_V1 WHERE NOTES = 'webapp'")
        ).scalar()
    engine.dispose()
    assert count == 0

    imported = authed_client.post(
        "/api/webapp/import", json={"dry_run": False, "delete_imported": True}
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 1
    assert imported.json()["deleted_from_sidecar"] == 1

    engine = create_engine(f"sqlite:///{mmex_settings.db_path}")
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT TRANSID, TRANSAMOUNT, NOTES FROM CHECKINGACCOUNT_V1 WHERE NOTES = 'webapp'"
            )
        ).fetchone()
    engine.dispose()
    assert row is not None
    assert str(row[1]).startswith("4.2")

    con = sqlite3.connect(sidecar)
    left = con.execute("SELECT COUNT(*) FROM New_Transaction").fetchone()[0]
    con.close()
    assert left == 1

    authed_client.post(f"/api/transactions/{int(row[0])}/delete")
