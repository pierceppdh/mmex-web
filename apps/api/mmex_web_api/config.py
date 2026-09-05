"""Runtime settings (env / `.env`)."""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    mmex_data_dir: Path = Path("data")
    mmex_db_path: Path | None = None
    mmex_lock_holder: str = "mmex-web"
    backup_keep: int = 14
    enable_openapi: bool = False
    static_dir: Path | None = None
    secret_key: str | None = None
    auth_username: str | None = None
    auth_password: str | None = None
    cookie_secure: bool = False
    session_max_age: int = 60 * 60 * 24 * 14
    locale_default: str = "fr"
    webapp_db_path: Path | None = None
    paperless_url: str = ""
    paperless_token: str = ""
    paperless_inbox_tag: str = "Nouveau-Relevé"
    paperless_done_tag: str = "Pointé"

    @field_validator(
        "paperless_url",
        "paperless_token",
        "paperless_inbox_tag",
        "paperless_done_tag",
        mode="before",
    )
    @classmethod
    def _strip_env(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @property
    def db_path(self) -> Path:
        if self.mmex_db_path is not None:
            return self.mmex_db_path
        return self.mmex_data_dir / "data.mmb"

    @property
    def lock_path(self) -> Path:
        return Path(str(self.db_path) + ".lock")

    @property
    def backups_dir(self) -> Path:
        return self.mmex_data_dir / "backups"

    @property
    def attachments_dir(self) -> Path:
        return self.mmex_data_dir / "attachments"

    @property
    def auth_file(self) -> Path:
        return self.mmex_data_dir / "auth.json"

    @property
    def secret_file(self) -> Path:
        return self.mmex_data_dir / ".secret_key"

    def resolved_webapp_db(self) -> Path | None:
        if self.webapp_db_path is not None:
            return self.webapp_db_path
        for candidate in (
            self.mmex_data_dir / "MMEX_New_Transaction.db",
            Path("/data/webmmxapp/MMEX_New_Transaction.db"),
        ):
            if candidate.is_file():
                return candidate
        return self.mmex_data_dir / "MMEX_New_Transaction.db"

    def resolved_static_dir(self) -> Path | None:
        if self.static_dir is not None:
            return self.static_dir
        here = Path(__file__).resolve().parent
        candidates = [
            Path("/app/static"),
            here.parents[2] / "apps" / "web" / "dist",
        ]
        for path in candidates:
            if path.is_dir() and (path / "index.html").is_file():
                return path
        return None


def load_settings() -> Settings:
    return Settings()
