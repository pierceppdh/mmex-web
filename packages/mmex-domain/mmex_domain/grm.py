"""General Report Manager: REPORT_V1, .grm zip import, SQL placeholders, HTML::Template (no Lua)."""

from __future__ import annotations

import html
import io
import re
import zipfile
from datetime import date, datetime
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from mmex_domain.transactions import _next_id

PLACEHOLDER_RE = re.compile(r"&([A-Za-z_][A-Za-z0-9_]*)")
PARAM_SAFE = re.compile(r"^[\w\-:\. ]*$")
TAG_RE = re.compile(
    r"(?is)(?:<!--\s*)?(</?TMPL_(?:VAR|LOOP|IF|UNLESS|ELSE)\b[^>]*?>)(?:\s*-->)?"
)
WRITE_HEAD = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|VACUUM|PRAGMA|GRANT)\b",
    re.I,
)


class GrmError(ValueError):
    """Invalid GRM payload, SQL, or template."""


def list_reports(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT REPORTID, REPORTNAME, GROUPNAME, IFNULL(ACTIVE, 1),
                       length(IFNULL(SQLCONTENT, '')), length(IFNULL(TEMPLATECONTENT, '')),
                       length(IFNULL(LUACONTENT, '')), DESCRIPTION
                  FROM REPORT_V1
                 ORDER BY GROUPNAME, REPORTNAME
                """
            )
        ).fetchall()
    return {
        "reports": [
            {
                "report_id": int(r[0]),
                "name": r[1],
                "group_name": r[2] or "",
                "active": int(r[3] or 1),
                "has_sql": int(r[4] or 0) > 0,
                "has_template": int(r[5] or 0) > 0,
                "has_lua": int(r[6] or 0) > 0,
                "description": (r[7] or "")[:400],
            }
            for r in rows
        ]
    }


def get_report(engine: Engine, report_id: int) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT REPORTID, REPORTNAME, GROUPNAME, IFNULL(ACTIVE, 1),
                       SQLCONTENT, TEMPLATECONTENT, LUACONTENT, DESCRIPTION
                  FROM REPORT_V1 WHERE REPORTID = :id
                """
            ),
            {"id": report_id},
        ).fetchone()
    if row is None:
        raise GrmError(f"unknown report {report_id}")
    sql = row[4] or ""
    return {
        "report_id": int(row[0]),
        "name": row[1],
        "group_name": row[2] or "",
        "active": int(row[3] or 1),
        "sql": sql,
        "has_lua": bool((row[6] or "").strip()),
        "description": row[7] or "",
        "placeholders": sorted(set(PLACEHOLDER_RE.findall(sql))),
    }


def delete_report(engine: Engine, report_id: int) -> None:
    with engine.begin() as conn:
        n = conn.execute(
            text("DELETE FROM REPORT_V1 WHERE REPORTID = :id"), {"id": report_id}
        ).rowcount
        if not n:
            raise GrmError(f"unknown report {report_id}")


def import_grm(engine: Engine, data: bytes, filename: str = "") -> dict[str, Any]:
    files = _read_zip(data)
    sql = files.get("sqlcontent.sql", "")
    tmpl = files.get("template.htt") or files.get("template.html") or ""
    lua = files.get("luacontent.lua", "")
    desc = files.get("description.txt", "")
    if not sql.strip() and not tmpl.strip():
        raise GrmError("zip must contain sqlcontent.sql or template.htt")
    name = _name_from_desc(desc) or _stem(filename) or "Imported report"
    group = ""
    with engine.begin() as conn:
        clash = conn.execute(
            text("SELECT REPORTID FROM REPORT_V1 WHERE REPORTNAME = :n COLLATE NOCASE"),
            {"n": name},
        ).fetchone()
        if clash is not None:
            name = f"{name} ({datetime.now().strftime('%Y%m%d%H%M%S')})"
        rid = _next_id(conn, "REPORT_V1", "REPORTID")
        conn.execute(
            text(
                """
                INSERT INTO REPORT_V1 (
                    REPORTID, REPORTNAME, GROUPNAME, ACTIVE,
                    SQLCONTENT, LUACONTENT, TEMPLATECONTENT, DESCRIPTION
                ) VALUES (:id, :n, :g, 1, :sql, :lua, :tmpl, :d)
                """
            ),
            {
                "id": rid,
                "n": name,
                "g": group,
                "sql": sql,
                "lua": lua,
                "tmpl": tmpl,
                "d": desc,
            },
        )
    return get_report(engine, rid)


def _stem(filename: str) -> str:
    base = (filename or "").replace("\\", "/").split("/")[-1]
    for ext in (".grm", ".zip"):
        if base.lower().endswith(ext):
            return base[: -len(ext)]
    return base


def _name_from_desc(desc: str) -> str:
    for line in (desc or "").splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return ""


def _read_zip(data: bytes) -> dict[str, str]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise GrmError("not a zip/grm archive") from exc
    out: dict[str, str] = {}
    for info in zf.infolist():
        if info.is_dir() or info.filename.startswith("__MACOSX"):
            continue
        name = info.filename.replace("\\", "/").split("/")[-1].lower()
        if not name:
            continue
        out[name] = zf.read(info).decode("utf-8", errors="replace")
    return out


def apply_placeholders(sql: str, params: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        val = params.get(key) or params.get(key.lower()) or ""
        if not PARAM_SAFE.fullmatch(str(val)):
            raise GrmError(f"invalid value for {key}")
        return str(val)

    return PLACEHOLDER_RE.sub(repl, sql)


def _one_select(sql: str) -> str:
    stripped = (sql or "").strip().rstrip(";").strip()
    if not stripped:
        raise GrmError("SQLCONTENT is empty")
    if ";" in stripped:
        raise GrmError("multiple SQL statements are not allowed")
    if WRITE_HEAD.match(stripped):
        raise GrmError("only SELECT/WITH queries are allowed")
    head = stripped.lstrip().upper()
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        raise GrmError("only SELECT/WITH queries are allowed")
    return stripped


def run_report(engine: Engine, report_id: int, params: dict[str, Any] | None = None) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT REPORTNAME, SQLCONTENT, TEMPLATECONTENT, LUACONTENT
                  FROM REPORT_V1 WHERE REPORTID = :id
                """
            ),
            {"id": report_id},
        ).fetchone()
        if row is None:
            raise GrmError(f"unknown report {report_id}")
        name, sql, tmpl, lua = row[0], row[1] or "", row[2] or "", row[3] or ""
        url = str(conn.engine.url)
    filled_params = _default_params(params or {})
    placeholders = sorted(set(PLACEHOLDER_RE.findall(sql)))
    filled_sql = apply_placeholders(sql, filled_params) if sql.strip() else ""
    columns: list[str] = []
    records: list[dict[str, Any]] = []
    if filled_sql:
        query = _one_select(filled_sql)
        records, columns = _query_readonly(url, query)
    ctx = _template_context(name, filled_params, columns, records, conn_engine=engine)
    html_out = render_template(tmpl, ctx) if tmpl.strip() else _fallback_html(name, columns, records)
    return {
        "report_id": report_id,
        "name": name,
        "placeholders": placeholders,
        "params": filled_params,
        "lua_skipped": bool(lua.strip()),
        "columns": columns,
        "rows": records[:500],
        "row_count": len(records),
        "html": html_out,
    }


def _default_params(raw: dict[str, Any]) -> dict[str, str]:
    today = date.today().isoformat()
    begin = str(raw.get("begin_date") or raw.get("date_from") or f"{date.today().year}-01-01")[:10]
    end = str(raw.get("end_date") or raw.get("date_to") or today)[:10]
    single = str(raw.get("single_date") or end)[:10]
    out = {
        "begin_date": begin,
        "end_date": end,
        "single_date": single,
        "single_time": str(raw.get("single_time") or "00:00:00"),
        "today": today,
        "filter": str(raw.get("filter") or ""),
    }
    for key, val in raw.items():
        if val is None:
            continue
        k = str(key)
        if k not in out:
            out[k] = str(val)[:80]
    return out


def _query_readonly(url: str, sql: str) -> tuple[list[dict[str, Any]], list[str]]:
    ro = create_engine(url)
    try:
        with ro.connect() as conn:
            conn.exec_driver_sql("PRAGMA query_only = ON")
            result = conn.exec_driver_sql(sql)
            cols = list(result.keys())
            records = []
            for raw in result.fetchall():
                item: dict[str, Any] = {}
                for key, val in zip(cols, raw):
                    sval = "" if val is None else str(val)
                    item[str(key)] = sval
                    item[str(key).upper()] = sval
                records.append(item)
            return records, cols
    except Exception as exc:
        raise GrmError(f"SQL error: {exc}") from exc
    finally:
        ro.dispose()


def _template_context(
    name: str,
    params: dict[str, str],
    columns: list[str],
    records: list[dict[str, Any]],
    conn_engine: Engine,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "REPORTNAME": name,
        "TODAY": datetime.now().strftime("%Y-%m-%d"),
        "CONTENTS": records,
        "ERRORS": [],
        "PFX_SYMBOL": "",
        "SFX_SYMBOL": "",
        "DECIMAL_POINT": ".",
        "GROUP_SEPARATOR": " ",
        "LANGUAGE": "fr",
        "ATTACHMENTSFOLDER": "",
        "FILESEPARATOR": "/",
        "HTMLSCALE": "100",
    }
    for key, val in params.items():
        ctx[key] = val
        ctx[key.upper()] = val
    with conn_engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT PFX_SYMBOL, SFX_SYMBOL, DECIMAL_POINT, GROUP_SEPARATOR, CURRENCY_SYMBOL
                  FROM CURRENCYFORMATS_V1
                 WHERE CURRENCYID = (
                       SELECT CAST(INFOVALUE AS INTEGER) FROM INFOTABLE_V1
                        WHERE INFONAME = 'BASECURRENCYID' LIMIT 1
                 )
                """
            )
        ).fetchone()
        if row:
            ctx["PFX_SYMBOL"] = row[0] or ""
            ctx["SFX_SYMBOL"] = row[1] or ""
            ctx["DECIMAL_POINT"] = row[2] or "."
            ctx["GROUP_SEPARATOR"] = row[3] or " "
            ctx["CURRENCY_SYMBOL"] = row[4] or ""
    return ctx


def _fallback_html(name: str, columns: list[str], records: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body = []
    for rec in records[:500]:
        tds = "".join(f"<td>{html.escape(str(rec.get(c, '')))}</td>" for c in columns)
        body.append(f"<tr>{tds}</tr>")
    return (
        "<!DOCTYPE html><html><body>"
        f"<h3>{html.escape(name)}</h3>"
        f"<table border='1'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></body></html>"
    )


def _parse_tag(raw: str) -> tuple[str, dict[str, str], bool]:
    inner = re.sub(r"^<!--\s*|\s*-->$", "", raw).strip()
    closing = inner.startswith("</")
    inner = re.sub(r"^</?TMPL_", "", inner, flags=re.I)
    inner = inner.rstrip(">").strip()
    parts = inner.split(None, 1)
    kind = parts[0].upper() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""
    attrs: dict[str, str] = {}
    for key, val in re.findall(r'([A-Za-z_]+)\s*=\s*"([^"]*)"', rest):
        attrs[key.upper()] = val
    for key, val in re.findall(r"([A-Za-z_]+)\s*=\s*'([^']*)'", rest):
        attrs.setdefault(key.upper(), val)
    for key, val in re.findall(r"([A-Za-z_]+)\s*=\s*([^\s>]+)", rest):
        attrs.setdefault(key.upper(), val.strip("\"'"))
    quoted = re.search(r'"([^"]+)"', rest)
    if quoted and "NAME" not in attrs:
        attrs["NAME"] = quoted.group(1)
    bare = rest.strip()
    if bare and "NAME" not in attrs and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", bare):
        attrs["NAME"] = bare
    return kind, attrs, closing


def _lookup(ctx: dict[str, Any], name: str | None) -> Any:
    if not name:
        return None
    if name in ctx:
        return ctx[name]
    up = name.upper()
    for key, val in ctx.items():
        if str(key).upper() == up:
            return val
    return None


def _extract_block(tmpl: str, start: int, kind: str) -> tuple[str, str, int]:
    depth = 1
    pos = start
    else_at: int | None = None
    while pos < len(tmpl):
        match = TAG_RE.search(tmpl, pos)
        if not match:
            raise GrmError(f"unclosed TMPL_{kind}")
        tag_kind, _attrs, closing = _parse_tag(match.group(1))
        if tag_kind == "ELSE" and depth == 1 and kind in {"IF", "UNLESS"} and else_at is None:
            else_at = match.start()
            pos = match.end()
            continue
        if tag_kind == kind and not closing:
            depth += 1
        elif tag_kind == kind and closing:
            depth -= 1
            if depth == 0:
                if else_at is None:
                    return tmpl[start : match.start()], "", match.end()
                else_match = TAG_RE.match(tmpl[else_at:])
                skip = else_match.end() if else_match else 0
                return tmpl[start:else_at], tmpl[else_at + skip : match.start()], match.end()
        pos = match.end()
    raise GrmError(f"unclosed TMPL_{kind}")


def render_template(tmpl: str, ctx: dict[str, Any]) -> str:
    out: list[str] = []
    pos = 0
    while pos < len(tmpl):
        match = TAG_RE.search(tmpl, pos)
        if not match:
            out.append(tmpl[pos:])
            break
        out.append(tmpl[pos : match.start()])
        kind, attrs, closing = _parse_tag(match.group(1))
        if kind == "VAR":
            val = _lookup(ctx, attrs.get("NAME"))
            if val is not None and not isinstance(val, list):
                text_val = str(val)
                if str(attrs.get("ESCAPE", "")).upper() in {"HTML", "1", "TRUE"}:
                    text_val = html.escape(text_val)
                out.append(text_val)
            pos = match.end()
            continue
        if kind == "LOOP" and not closing:
            body, _alt, end = _extract_block(tmpl, match.end(), "LOOP")
            items = _lookup(ctx, attrs.get("NAME")) or []
            if isinstance(items, list):
                for item in items:
                    nested = dict(ctx)
                    if isinstance(item, dict):
                        nested.update(item)
                    out.append(render_template(body, nested))
            pos = end
            continue
        if kind in {"IF", "UNLESS"} and not closing:
            body, alt, end = _extract_block(tmpl, match.end(), kind)
            truthy = bool(_lookup(ctx, attrs.get("NAME")))
            if kind == "UNLESS":
                truthy = not truthy
            out.append(render_template(body if truthy else alt, ctx))
            pos = end
            continue
        if kind == "ELSE":
            pos = match.end()
            continue
        pos = match.end()
    return "".join(out)
