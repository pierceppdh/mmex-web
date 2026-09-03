from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from mmex_domain.grm import apply_placeholders, render_template
from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def _zip(*parts: tuple[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in parts:
            zf.writestr(name, content)
    return buf.getvalue()


def test_template_loop_and_placeholders() -> None:
    html = render_template(
        "<h3><TMPL_VAR REPORTNAME></h3><TMPL_LOOP NAME=CONTENTS>"
        "<p><TMPL_VAR ACCOUNTNAME></p></TMPL_LOOP>",
        {"REPORTNAME": "Demo", "CONTENTS": [{"ACCOUNTNAME": "Courant"}]},
    )
    assert "Demo" in html
    assert "Courant" in html
    sql = apply_placeholders(
        "SELECT * FROM t WHERE d <= '&single_date'", {"single_date": "2026-08-01"}
    )
    assert sql == "SELECT * FROM t WHERE d <= '2026-08-01'"


def test_import_run_reject_write(authed_client: TestClient, mmex_settings: Settings) -> None:
    _seed(mmex_settings)
    payload = _zip(
        ("description.txt", "PR10 Test\nA sample GRM."),
        (
            "sqlcontent.sql",
            "SELECT '&begin_date' AS BEGIN_DATE, ACCOUNTNAME FROM ACCOUNTLIST_V1 "
            "WHERE STATUS = 'Open' ORDER BY ACCOUNTNAME LIMIT 5;",
        ),
        (
            "template.htt",
            "<h3><TMPL_VAR REPORTNAME></h3>"
            "<TMPL_LOOP NAME=CONTENTS><div><TMPL_VAR ACCOUNTNAME> "
            "<TMPL_VAR BEGIN_DATE></div></TMPL_LOOP>",
        ),
        ("luacontent.lua", "function complete(result) end"),
    )
    imported = authed_client.post(
        "/api/grm/import", files={"file": ("sample.grm", payload, "application/zip")}
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["name"] == "PR10 Test"
    assert "begin_date" in body["placeholders"]
    rid = body["report_id"]

    listed = authed_client.get("/api/grm").json()["reports"]
    assert any(r["report_id"] == rid and r["has_lua"] for r in listed)

    ran = authed_client.post(
        f"/api/grm/{rid}/run",
        json={"begin_date": "2026-01-01", "end_date": "2026-08-29"},
    )
    assert ran.status_code == 200, ran.text
    out = ran.json()
    assert out["lua_skipped"] is True
    assert out["row_count"] >= 1
    assert "Courant" in out["html"]
    assert "2026-01-01" in out["html"]

    evil = _zip(("sqlcontent.sql", "INSERT INTO PAYEE_V1 (PAYEEID, PAYEENAME) VALUES (99, 'x');"))
    bad_imp = authed_client.post(
        "/api/grm/import", files={"file": ("evil.grm", evil, "application/zip")}
    )
    assert bad_imp.status_code == 200
    evil_id = bad_imp.json()["report_id"]
    blocked = authed_client.post(f"/api/grm/{evil_id}/run", json={})
    assert blocked.status_code == 400
    assert "SELECT" in blocked.json()["detail"]

    assert authed_client.delete(f"/api/grm/{rid}").status_code == 200
    assert authed_client.get(f"/api/grm/{rid}").status_code == 404
