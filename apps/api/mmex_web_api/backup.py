"""Copy-on-start (and later, pre-upgrade) backups of the `.mmb` file."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def backup_database(db_path: Path, backups_dir: Path, keep: int = 14) -> Path | None:
    """Snapshot `db_path` into `backups_dir` before a write. Returns the new file, or None if missing."""
    if not db_path.is_file():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = backups_dir / f"{db_path.name}_{stamp}.bak"
    suffix = 1
    while dest.exists():
        dest = backups_dir / f"{db_path.name}_{stamp}_{suffix}.bak"
        suffix += 1
    copied = False
    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            copied = True
        finally:
            dst.close()
            src.close()
    except sqlite3.Error:
        copied = False
    if not copied:
        shutil.copy2(db_path, dest)
        for extra in ("-wal", "-shm"):
            side = Path(str(db_path) + extra)
            if side.is_file():
                shutil.copy2(side, Path(str(dest) + extra))
    prune_backups(backups_dir, prefix=f"{db_path.name}_", keep=keep)
    return dest


def prune_backups(backups_dir: Path, prefix: str, keep: int) -> None:
    if keep < 1 or not backups_dir.is_dir():
        return
    files = sorted(
        (p for p in backups_dir.iterdir() if p.is_file() and p.name.startswith(prefix)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in files[keep:]:
        stale.unlink(missing_ok=True)


def latest_backup(backups_dir: Path) -> dict | None:
    if not backups_dir.is_dir():
        return None
    files = [p for p in backups_dir.iterdir() if p.is_file() and p.suffix == ".bak"]
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    return {
        "path": str(newest),
        "size": newest.stat().st_size,
        "mtime_iso": datetime.fromtimestamp(newest.stat().st_mtime).isoformat(
            timespec="seconds"
        ),
    }
