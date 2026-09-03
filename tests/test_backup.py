from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from mmex_web_api.backup import backup_database, prune_backups
from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def test_backup_copies_and_prunes(tmp_path: Path) -> None:
    db = tmp_path / "data.mmb"
    db.write_bytes(b"sqlite")
    backups = tmp_path / "backups"
    created: list[Path] = []
    for i in range(3):
        dest = backup_database(db, backups, keep=100)
        assert dest is not None
        os.utime(dest, (1_700_000_000 + i, 1_700_000_000 + i))
        created.append(dest)
    prune_backups(backups, prefix="data.mmb_", keep=2)
    remaining = set(backups.glob("*.bak"))
    assert created[0] not in remaining
    assert created[1] in remaining
    assert created[2] in remaining


def test_backup_missing_db_returns_none(tmp_path: Path) -> None:
    assert backup_database(tmp_path / "missing.mmb", tmp_path / "backups") is None


def test_prune_noop_on_empty(tmp_path: Path) -> None:
    prune_backups(tmp_path / "nope", prefix="data.mmb_", keep=14)


def test_write_creates_backup_first(authed_client: TestClient, mmex_settings: Settings) -> None:
    _seed(mmex_settings)
    backups = mmex_settings.backups_dir
    before = set(backups.glob("*.bak")) if backups.is_dir() else set()
    created = authed_client.post(
        "/api/payees",
        json={"name": "Backup Probe", "categ_id": 1},
    )
    assert created.status_code == 200, created.text
    after = set(backups.glob("*.bak"))
    assert after - before, "expected a new .bak before the write"
