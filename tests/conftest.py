from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from mmex_domain.models import Base
from mmex_web_api.config import Settings
from mmex_web_api.main import create_app


def make_mmex_db(path: Path, user_version: int = 21) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(f"PRAGMA user_version = {int(user_version)}"))
        conn.execute(
            text(
                "INSERT INTO INFOTABLE_V1 (INFONAME, INFOVALUE) VALUES "
                "('DATAVERSION', '3'), ('MMEXVERSION', '1.9.3'), "
                "('BASECURRENCYID', '1'), ('BASECURRENCYNAME', 'Euro'), "
                "('USERNAME', 'test'), ('USECURRENCYHISTORY', 'FALSE')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO CURRENCYFORMATS_V1 (
                    CURRENCYID, CURRENCYNAME, PFX_SYMBOL, SFX_SYMBOL,
                    DECIMAL_POINT, GROUP_SEPARATOR, UNIT_NAME, CENT_NAME,
                    SCALE, BASECONVRATE, CURRENCY_SYMBOL, CURRENCY_TYPE
                ) VALUES
                (1, 'Euro', '', ' €', ',', ' ', 'euro', 'cent', 100, 1, 'EUR', 'Fiat'),
                (2, 'US dollar', '$', '', '.', ',', 'Dollar', 'Cent', 100, 0.9, 'USD', 'Fiat')
                """
            )
        )
    engine.dispose()
    return path


@pytest.fixture
def mmex_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    db_path = data / "data.mmb"
    make_mmex_db(db_path)
    return Settings(
        mmex_data_dir=data,
        mmex_db_path=db_path,
        enable_openapi=False,
        secret_key="unit-test-secret-key-not-for-production",
        auth_username="mmex",
        auth_password="secret",
    )


def login(client, username: str = "mmex", password: str = "secret"):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp


@pytest.fixture
def authed_client(client):
    login(client)
    return client


@pytest.fixture
def client(mmex_settings: Settings):
    app = create_app(mmex_settings)
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
