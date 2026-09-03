"""Local username/password store and session helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from pathlib import Path

from mmex_web_api.config import Settings

logger = logging.getLogger(__name__)

PBKDF2_ROUNDS = 200_000
SESSION_USER_KEY = "username"
MIN_PASSWORD_LEN = 8


class AuthStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._file_record: dict[str, str] | None = None
        if settings.auth_file.is_file():
            try:
                data = json.loads(settings.auth_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("username") and data.get("hash"):
                    self._file_record = {str(k): str(v) for k, v in data.items()}
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not read auth file: %s", exc)

    @property
    def env_configured(self) -> bool:
        user = (self.settings.auth_username or "").strip()
        password = self.settings.auth_password or ""
        return bool(user and password)

    def needs_bootstrap(self) -> bool:
        return not self.env_configured and self._file_record is None

    def has_credentials(self) -> bool:
        return self.env_configured or self._file_record is not None

    def verify(self, username: str, password: str) -> bool:
        if self.env_configured:
            expected_user = (self.settings.auth_username or "").strip()
            expected_password = self.settings.auth_password or ""
            return hmac.compare_digest(username, expected_user) and hmac.compare_digest(
                password, expected_password
            )
        if self._file_record is None:
            return False
        if not hmac.compare_digest(username, self._file_record["username"]):
            return False
        salt = bytes.fromhex(self._file_record["salt"])
        expected = self._file_record["hash"]
        actual = _hash_password(password, salt)
        return hmac.compare_digest(actual, expected)

    def bootstrap(self, username: str, password: str) -> None:
        if not self.needs_bootstrap():
            raise ValueError("credentials already exist")
        username = username.strip()
        if not username:
            raise ValueError("username required")
        if len(password) < MIN_PASSWORD_LEN:
            raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
        salt = secrets.token_bytes(16)
        record = {
            "username": username,
            "salt": salt.hex(),
            "hash": _hash_password(password, salt),
        }
        path = self.settings.auth_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        self._file_record = record


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS
    ).hex()


def resolve_secret_key(settings: Settings) -> str:
    if settings.secret_key:
        return settings.secret_key
    path: Path = settings.secret_file
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    key = secrets.token_urlsafe(48)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key + "\n", encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        logger.warning("Could not persist secret key to %s", path)
    return key
