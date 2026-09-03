"""CSV / QIF / XML import and export (desktop univ CSV + QIF).

CSV/XML share the universal field list. The MMEX standard column order is
ID, Date, Status, Type, Account, Payee, Category, SubCategory, Amount,
Currency, Number, Notes. XML is Excel 2003 Spreadsheet. QIF uses Bank-type
records (D/T/P/L/M/N/C/^). Import auto-creates missing payees, categories,
and tags. Dry-run parses without writing.
"""

from __future__ import annotations

import csv
import io
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree as ET

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.constants import NOT_SET, REF_TRANSACTION, STATUS_CYCLE
from mmex_domain.lookups import _category_path
from mmex_domain.money import as_decimal

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 5000
SS_NS = "urn:schemas-microsoft-com:office:spreadsheet"

FIELDS = (
    "id",
    "date",
    "status",
    "type",
    "account",
    "payee",
    "amount",
    "currency",
    "category",
    "subcategory",
    "tags",
    "number",
    "notes",
    "skip",
    "withdrawal",
    "deposit",
    "balance",
)
MMEX_FORMAT = (
    "id",
    "date",
    "status",
    "type",
    "account",
    "payee",
    "category",
    "subcategory",
    "amount",
    "currency",
    "number",
    "notes",
)
DATE_FORMATS = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
    "YYYY/MM/DD": "%Y/%m/%d",
    "DD.MM.YYYY": "%d.%m.%Y",
    "DD-MM-YYYY": "%d-%m-%Y",
}
STATUS_MAP = {
    "": "",
    "n": "",
    "none": "",
    "r": "R",
    "reconciled": "R",
    "*": "R",
    "x": "R",
    "c": "R",
    "cleared": "R",
    "v": "V",
    "void": "V",
    "f": "F",
    "follow up": "F",
    "followup": "F",
    "d": "D",
    "duplicate": "D",
}


class IoError(ValueError):
    """Invalid import/export payload."""


def _next_id(conn: Connection, table: str, column: str) -> int:
    now_based = int(time.time() * 1000) * 1000
    max_id = int(conn.execute(text(f"SELECT MAX({column}) FROM {table}")).scalar() or 0)
    return max(now_based, max_id + 1)


def meta() -> dict[str, Any]:
    return {
        "formats": ["csv", "qif", "xml"],
        "fields": list(FIELDS),
        "mmex_format": list(MMEX_FORMAT),
        "date_formats": list(DATE_FORMATS),
        "delimiters": [",", ";", "\\t", "|"],
        "amount_signs": ["deposit", "withdrawal"],
    }


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _parse_date(raw: str, fmt_key: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise IoError("date is required")
    if "T" in value:
        value = value.split("T", 1)[0]
    value = value.replace("'", "-")
    fmt = DATE_FORMATS.get(fmt_key, "%Y-%m-%d")
    tried = [fmt, "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d.%m.%Y", "%d-%m-%Y"]
    seen: set[str] = set()
    for candidate in tried:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return datetime.strptime(value[:10], candidate).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise IoError(f"invalid date {raw!r}")


def _parse_amount(raw: str, decimal: str) -> Decimal:
    text_val = (raw or "").strip()
    if not text_val:
        return Decimal("0")
    text_val = text_val.replace(" ", "")
    if decimal == ",":
        text_val = text_val.replace(".", "").replace(",", ".")
    else:
        if text_val.count(",") == 1 and text_val.count(".") == 0:
            text_val = text_val.replace(",", ".")
        else:
            text_val = text_val.replace(",", "")
    text_val = re.sub(r"[^0-9.\-]", "", text_val)
    if text_val in ("", "-", "."):
        return Decimal("0")
    try:
        return Decimal(text_val)
    except InvalidOperation as exc:
        raise IoError(f"invalid amount {raw!r}") from exc


def _status(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in STATUS_MAP:
        return STATUS_MAP[key]
    if raw in STATUS_CYCLE:
        return raw
    return ""


def _type_from_token(raw: str) -> str | None:
    key = (raw or "").strip().lower()
    if key in ("withdrawal", "withdraw", "debit", "expense", "dépense", "depense"):
        return "Withdrawal"
    if key in ("deposit", "credit", "income", "recette"):
        return "Deposit"
    if key in ("transfer", "virement"):
        return "Transfer"
    return None


def parse_fields(raw: object) -> list[str]:
    if raw is None or raw == "":
        return list(MMEX_FORMAT)
    if isinstance(raw, list):
        keys = [str(x).strip().lower() for x in raw]
    else:
        keys = [p.strip().lower() for p in str(raw).split(",") if p.strip()]
    out: list[str] = []
    for key in keys:
        if key in ("don't care", "dontcare", "dont_care"):
            key = "skip"
        if key == "transnum":
            key = "number"
        if key not in FIELDS:
            raise IoError(f"unknown field {key}")
        out.append(key)
    if "date" not in out:
        raise IoError("date field is required")
    if "amount" not in out and not ("withdrawal" in out and "deposit" in out):
        raise IoError("amount or withdrawal+deposit is required")
    return out


def _split_csv(text_val: str, delimiter: str) -> list[list[str]]:
    delim = "\t" if delimiter in ("\\t", "\t") else (delimiter or ",")
    reader = csv.reader(io.StringIO(text_val), delimiter=delim)
    return [list(row) for row in reader]


def _split_xml(text_val: str) -> list[list[str]]:
    try:
        root = ET.fromstring(text_val)
    except ET.ParseError as exc:
        raise IoError("invalid XML") from exc
    rows: list[list[str]] = []
    for row_el in root.iter():
        tag = row_el.tag.split("}")[-1]
        if tag != "Row":
            continue
        cells: dict[int, str] = {}
        index = 1
        for cell in list(row_el):
            ctag = cell.tag.split("}")[-1]
            if ctag != "Cell":
                continue
            idx_attr = (
                cell.attrib.get(f"{{{SS_NS}}}Index")
                or cell.attrib.get("ss:Index")
                or cell.attrib.get("Index")
            )
            if idx_attr:
                index = int(idx_attr)
            value = ""
            for data in list(cell):
                dtag = data.tag.split("}")[-1]
                if dtag == "Data":
                    value = "".join(data.itertext())
                    break
            if not value:
                value = "".join(cell.itertext())
            cells[index] = value
            index += 1
        if cells:
            width = max(cells)
            rows.append([cells.get(i, "") for i in range(1, width + 1)])
    if not rows:
        raise IoError("XML has no data rows")
    return rows


def _parse_qif(text_val: str, date_fmt: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    header = ""
    for raw_line in text_val.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        code, data = line[0], line[1:]
        if code == "!":
            header = data
            continue
        if header.lower().startswith("type:invst") or header.lower().startswith("type:cat"):
            if code == "^":
                cur = {}
            continue
        if code == "^":
            if cur:
                records.append(cur)
            cur = {}
            continue
        if code == "D":
            cur["date"] = data
        elif code == "T" or code == "U":
            cur["amount"] = data
        elif code == "P":
            cur["payee"] = data
        elif code == "M":
            cur["notes"] = data
        elif code == "N":
            cur["number"] = data
        elif code == "L":
            cur["category"] = data
        elif code == "C":
            cur["status"] = data
        elif code == "S":
            cur.setdefault("notes", "")
        elif code in ("E", "$"):
            continue
    if cur:
        records.append(cur)
    out_rows: list[dict[str, str]] = []
    for rec in records:
        cat = rec.get("category") or ""
        account = ""
        if cat.startswith("[") and "]" in cat:
            account = cat.strip("[]")
            cat = ""
            rec["type"] = "Transfer"
        rec["category"] = cat
        rec["account"] = account
        out_rows.append(rec)
    return out_rows


def _table_from_file(data: bytes, fmt: str, delimiter: str) -> list[list[str]]:
    text_val = _decode(data)
    if fmt == "csv":
        return _split_csv(text_val, delimiter)
    if fmt == "xml":
        return _split_xml(text_val)
    raise IoError("use qif parser")


def _account(conn: Connection, account_id: int) -> dict[str, Any]:
    row = conn.execute(
        text(
            "SELECT ACCOUNTID, ACCOUNTNAME, ACCOUNTTYPE, CURRENCYID, STATUS "
            "FROM ACCOUNTLIST_V1 WHERE ACCOUNTID = :id"
        ),
        {"id": account_id},
    ).fetchone()
    if row is None:
        raise IoError("unknown account")
    return {
        "account_id": int(row[0]),
        "name": row[1],
        "account_type": row[2],
        "currency_id": int(row[3]),
        "status": row[4],
    }


def _account_by_name(conn: Connection, name: str) -> int | None:
    row = conn.execute(
        text("SELECT ACCOUNTID FROM ACCOUNTLIST_V1 WHERE ACCOUNTNAME = :n COLLATE NOCASE"),
        {"n": name},
    ).fetchone()
    return int(row[0]) if row else None


def _ensure_payee(conn: Connection, name: str) -> tuple[int, bool]:
    label = (name or "").strip() or "Unknown"
    row = conn.execute(
        text("SELECT PAYEEID FROM PAYEE_V1 WHERE PAYEENAME = :n COLLATE NOCASE"),
        {"n": label},
    ).fetchone()
    if row:
        return int(row[0]), False
    pid = _next_id(conn, "PAYEE_V1", "PAYEEID")
    conn.execute(
        text(
            "INSERT INTO PAYEE_V1 (PAYEEID, PAYEENAME, CATEGID, ACTIVE) "
            "VALUES (:id, :name, :cid, 1)"
        ),
        {"id": pid, "name": label, "cid": NOT_SET},
    )
    return pid, True


def _ensure_category(conn: Connection, path: str) -> tuple[int, bool]:
    parts = [p.strip() for p in path.split(":") if p.strip()]
    if not parts:
        return NOT_SET, False
    created = False
    parent = NOT_SET
    cid = NOT_SET
    for part in parts:
        row = conn.execute(
            text(
                "SELECT CATEGID FROM CATEGORY_V1 "
                "WHERE CATEGNAME = :n COLLATE NOCASE AND IFNULL(PARENTID, -1) = :p"
            ),
            {"n": part, "p": parent},
        ).fetchone()
        if row:
            cid = int(row[0])
        else:
            cid = _next_id(conn, "CATEGORY_V1", "CATEGID")
            conn.execute(
                text(
                    "INSERT INTO CATEGORY_V1 (CATEGID, CATEGNAME, ACTIVE, PARENTID) "
                    "VALUES (:id, :name, 1, :pid)"
                ),
                {"id": cid, "name": part, "pid": parent},
            )
            created = True
        parent = cid
    return cid, created


def _ensure_tags(conn: Connection, names: str) -> tuple[list[int], int]:
    created = 0
    ids: list[int] = []
    for raw in names.replace(",", ";").split(";"):
        label = raw.strip()
        if not label:
            continue
        row = conn.execute(
            text("SELECT TAGID FROM TAG_V1 WHERE TAGNAME = :n COLLATE NOCASE"),
            {"n": label},
        ).fetchone()
        if row:
            ids.append(int(row[0]))
            continue
        tid = _next_id(conn, "TAG_V1", "TAGID")
        conn.execute(
            text("INSERT INTO TAG_V1 (TAGID, TAGNAME, ACTIVE) VALUES (:id, :name, 1)"),
            {"id": tid, "name": label},
        )
        ids.append(tid)
        created += 1
    return ids, created


def _holder_from_map(
    mapped: dict[str, str],
    *,
    date_fmt: str,
    decimal: str,
    amount_sign: str,
    deposit_word: str,
) -> dict[str, Any]:
    day = _parse_date(mapped.get("date") or "", date_fmt)
    status = _status(mapped.get("status") or "")
    notes = mapped.get("notes") or ""
    number = mapped.get("number") or ""
    payee = mapped.get("payee") or ""
    cat = mapped.get("category") or ""
    sub = mapped.get("subcategory") or ""
    if sub:
        cat = f"{cat}:{sub}" if cat else sub
    dest_name = mapped.get("account") or ""
    if cat.startswith("[") and "]" in cat:
        dest_name = cat.strip("[]")
        cat = ""
    tags = mapped.get("tags") or ""
    typed = _type_from_token(mapped.get("type") or "")
    if mapped.get("type") and deposit_word and mapped["type"].strip().lower() == deposit_word.lower():
        typed = "Deposit"
    wd = _parse_amount(mapped.get("withdrawal") or "", decimal)
    dep = _parse_amount(mapped.get("deposit") or "", decimal)
    amt = _parse_amount(mapped.get("amount") or "", decimal)
    if "withdrawal" in mapped or "deposit" in mapped:
        if wd and not dep:
            typed = typed or "Withdrawal"
            amt = abs(wd)
        elif dep and not wd:
            typed = typed or "Deposit"
            amt = abs(dep)
        elif wd or dep:
            if wd >= dep:
                typed = typed or "Withdrawal"
                amt = abs(wd)
            else:
                typed = typed or "Deposit"
                amt = abs(dep)
    elif typed is None:
        if amount_sign == "withdrawal":
            if amt > 0:
                typed = "Withdrawal"
            elif amt < 0:
                typed = "Deposit"
                amt = abs(amt)
            else:
                typed = "Withdrawal"
        else:
            if amt < 0:
                typed = "Withdrawal"
                amt = abs(amt)
            else:
                typed = "Deposit"
    else:
        amt = abs(amt)
    if dest_name and typed != "Transfer" and not payee:
        typed = "Transfer"
    if typed is None:
        typed = "Withdrawal"
    if amt == 0 and typed != "Transfer":
        raise IoError("invalid amount")
    return {
        "date": day,
        "status": status,
        "type": typed,
        "payee": payee,
        "category": cat,
        "account": dest_name,
        "tags": tags,
        "number": number,
        "notes": notes,
        "amount": amt,
    }


def _insert_txn(
    conn: Connection,
    *,
    account_id: int,
    holder: dict[str, Any],
) -> int:
    code = holder["type"]
    dest = NOT_SET
    payee_id = NOT_SET
    if code == "Transfer":
        if holder["account"]:
            found = _account_by_name(conn, holder["account"])
            if found is None:
                raise IoError(f"unknown transfer account {holder['account']!r}")
            dest = found
        payee_id = NOT_SET
    else:
        payee_id, _ = _ensure_payee(conn, holder["payee"])
    categ_id = NOT_SET
    if holder["category"]:
        categ_id, _ = _ensure_category(conn, holder["category"])
    tag_ids, _ = _ensure_tags(conn, holder["tags"])
    trans_id = _next_id(conn, "CHECKINGACCOUNT_V1", "TRANSID")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    amt = str(holder["amount"])
    conn.execute(
        text(
            """
            INSERT INTO CHECKINGACCOUNT_V1 (
                TRANSID, ACCOUNTID, TOACCOUNTID, PAYEEID, TRANSCODE, TRANSAMOUNT,
                STATUS, TRANSACTIONNUMBER, NOTES, CATEGID, TRANSDATE,
                LASTUPDATEDTIME, DELETEDTIME, FOLLOWUPID, TOTRANSAMOUNT, COLOR
            ) VALUES (
                :tid, :aid, :toid, :pid, :code, :amt, :status, :num, :notes,
                :cid, :tdate, :upd, '', -1, :toamt, -1
            )
            """
        ),
        {
            "tid": trans_id,
            "aid": account_id,
            "toid": dest,
            "pid": payee_id,
            "code": code,
            "amt": amt,
            "status": holder["status"],
            "num": holder["number"],
            "notes": holder["notes"],
            "cid": categ_id,
            "tdate": holder["date"] + "T00:00:00",
            "upd": now,
            "toamt": amt,
        },
    )
    for tid in tag_ids:
        conn.execute(
            text(
                "INSERT INTO TAGLINK_V1 (REFTYPE, REFID, TAGID) VALUES (:t, :rid, :tag)"
            ),
            {"t": REF_TRANSACTION, "rid": trans_id, "tag": tid},
        )
    return trans_id


def import_file(
    engine: Engine,
    data: bytes,
    *,
    fmt: str,
    account_id: int,
    fields: object = None,
    delimiter: str = ",",
    date_format: str = "YYYY-MM-DD",
    decimal: str = ".",
    amount_sign: str = "deposit",
    skip_first: int = 0,
    skip_last: int = 0,
    dry_run: bool = False,
    deposit_word: str = "Deposit",
) -> dict[str, Any]:
    if len(data) > MAX_BYTES:
        raise IoError("file too large")
    fmt = (fmt or "csv").lower()
    if fmt not in ("csv", "qif", "xml"):
        raise IoError("format must be csv, qif or xml")
    skip_first = max(0, int(skip_first or 0))
    skip_last = max(0, int(skip_last or 0))
    field_list = parse_fields(fields) if fmt != "qif" else list(MMEX_FORMAT)
    created_payees = 0
    created_cats = 0
    created_tags = 0
    imported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    preview: list[dict[str, Any]] = []

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            _account(conn, account_id)
            if fmt == "qif":
                records = _parse_qif(_decode(data), date_format)
                work = records[skip_first : len(records) - skip_last if skip_last else None]
                if len(work) > MAX_ROWS:
                    raise IoError("too many rows")
                for i, rec in enumerate(work, start=skip_first + 1):
                    try:
                        holder = _holder_from_map(
                            rec,
                            date_fmt=date_format,
                            decimal=decimal,
                            amount_sign=amount_sign,
                            deposit_word=deposit_word,
                        )
                        preview.append({"line": i, "parsed": holder, "error": None})
                        if not dry_run:
                            before_p = conn.execute(text("SELECT COUNT(*) FROM PAYEE_V1")).scalar()
                            before_c = conn.execute(text("SELECT COUNT(*) FROM CATEGORY_V1")).scalar()
                            before_t = conn.execute(text("SELECT COUNT(*) FROM TAG_V1")).scalar()
                            tid = _insert_txn(conn, account_id=account_id, holder=holder)
                            created_payees += int(
                                conn.execute(text("SELECT COUNT(*) FROM PAYEE_V1")).scalar() or 0
                            ) - int(before_p or 0)
                            created_cats += int(
                                conn.execute(text("SELECT COUNT(*) FROM CATEGORY_V1")).scalar() or 0
                            ) - int(before_c or 0)
                            created_tags += int(
                                conn.execute(text("SELECT COUNT(*) FROM TAG_V1")).scalar() or 0
                            ) - int(before_t or 0)
                            imported.append({"line": i, "trans_id": tid})
                    except (IoError, ValueError) as exc:
                        errors.append({"line": i, "error": str(exc)})
                        preview.append({"line": i, "parsed": rec, "error": str(exc)})
            else:
                table = _table_from_file(data, fmt, delimiter)
                end = len(table) - skip_last if skip_last else len(table)
                work = table[skip_first:end]
                if len(work) > MAX_ROWS:
                    raise IoError("too many rows")
                for i, row in enumerate(work, start=skip_first + 1):
                    mapped: dict[str, str] = {}
                    for idx, key in enumerate(field_list):
                        if key == "skip":
                            continue
                        mapped[key] = row[idx] if idx < len(row) else ""
                    if not any((v or "").strip() for v in mapped.values()):
                        continue
                    try:
                        holder = _holder_from_map(
                            mapped,
                            date_fmt=date_format,
                            decimal=decimal,
                            amount_sign=amount_sign,
                            deposit_word=deposit_word,
                        )
                        preview.append(
                            {
                                "line": i,
                                "parsed": {**holder, "amount": str(holder["amount"])},
                                "error": None,
                            }
                        )
                        if not dry_run:
                            before_p = conn.execute(text("SELECT COUNT(*) FROM PAYEE_V1")).scalar()
                            before_c = conn.execute(text("SELECT COUNT(*) FROM CATEGORY_V1")).scalar()
                            before_t = conn.execute(text("SELECT COUNT(*) FROM TAG_V1")).scalar()
                            tid = _insert_txn(conn, account_id=account_id, holder=holder)
                            created_payees += int(
                                conn.execute(text("SELECT COUNT(*) FROM PAYEE_V1")).scalar() or 0
                            ) - int(before_p or 0)
                            created_cats += int(
                                conn.execute(text("SELECT COUNT(*) FROM CATEGORY_V1")).scalar() or 0
                            ) - int(before_c or 0)
                            created_tags += int(
                                conn.execute(text("SELECT COUNT(*) FROM TAG_V1")).scalar() or 0
                            ) - int(before_t or 0)
                            imported.append({"line": i, "trans_id": tid})
                    except (IoError, ValueError) as exc:
                        errors.append({"line": i, "error": str(exc)})
                        preview.append({"line": i, "parsed": mapped, "error": str(exc)})
            if dry_run:
                trans.rollback()
                imported = []
                created_payees = created_cats = created_tags = 0
            else:
                trans.commit()
        except Exception:
            if trans.is_active:
                trans.rollback()
            raise

    for row in preview:
        parsed = row.get("parsed")
        if isinstance(parsed, dict) and "amount" in parsed and not isinstance(parsed["amount"], str):
            parsed["amount"] = str(parsed["amount"])
    return {
        "format": fmt,
        "dry_run": dry_run,
        "imported": len(imported),
        "errors": errors,
        "created": {
            "payees": created_payees,
            "categories": created_cats,
            "tags": created_tags,
        },
        "transactions": imported,
        "preview": preview[:50],
    }


def _export_rows(
    engine: Engine,
    account_id: int,
    *,
    date_from: str | None,
    date_to: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with engine.connect() as conn:
        acct = _account(conn, account_id)
        cats = {
            int(r[0]): {"categ_id": int(r[0]), "name": r[1], "parent_id": int(r[2]) if r[2] and int(r[2]) > 0 else None}
            for r in conn.execute(text("SELECT CATEGID, CATEGNAME, PARENTID FROM CATEGORY_V1"))
        }
        cur = conn.execute(
            text("SELECT CURRENCY_SYMBOL FROM CURRENCYFORMATS_V1 WHERE CURRENCYID = :id"),
            {"id": acct["currency_id"]},
        ).fetchone()
        symbol = cur[0] if cur else ""
        sql = """
            SELECT c.TRANSID, c.TRANSDATE, c.STATUS, c.TRANSCODE, c.PAYEEID, p.PAYEENAME,
                   c.CATEGID, c.TRANSAMOUNT, c.TRANSACTIONNUMBER, c.NOTES, c.TOACCOUNTID,
                   a2.ACCOUNTNAME
              FROM CHECKINGACCOUNT_V1 c
              LEFT JOIN PAYEE_V1 p ON p.PAYEEID = c.PAYEEID
              LEFT JOIN ACCOUNTLIST_V1 a2 ON a2.ACCOUNTID = c.TOACCOUNTID
             WHERE c.ACCOUNTID = :aid
               AND (c.DELETEDTIME IS NULL OR c.DELETEDTIME = '')
        """
        params: dict[str, Any] = {"aid": account_id}
        if date_from:
            sql += " AND date(c.TRANSDATE) >= :a"
            params["a"] = date_from[:10]
        if date_to:
            sql += " AND date(c.TRANSDATE) <= :b"
            params["b"] = date_to[:10]
        sql += " ORDER BY c.TRANSDATE, c.TRANSID"
        rows = conn.execute(text(sql), params).fetchall()
        tag_map: dict[int, list[str]] = {}
        ids = [int(r[0]) for r in rows]
        if ids:
            q = text(
                "SELECT l.REFID, t.TAGNAME FROM TAGLINK_V1 l "
                "JOIN TAG_V1 t ON t.TAGID = l.TAGID "
                "WHERE l.REFTYPE = :rt AND l.REFID IN :ids"
            ).bindparams(bindparam("ids", expanding=True))
            for rid, name in conn.execute(q, {"rt": REF_TRANSACTION, "ids": ids}):
                tag_map.setdefault(int(rid), []).append(name)
    out = []
    for r in rows:
        trans_id = int(r[0])
        date_s = str(r[1] or "")[:10]
        code = r[3]
        payee = r[5] or ""
        cid = int(r[6]) if r[6] is not None and int(r[6]) > 0 else NOT_SET
        path = _category_path(cid, cats) if cid in cats else ""
        if " : " in path:
            parts = path.split(" : ")
            cat, sub = parts[0], " : ".join(parts[1:])
        else:
            cat, sub = path, ""
        amount = as_decimal(r[7])
        if code == "Withdrawal":
            signed = -amount
        elif code == "Deposit":
            signed = amount
        else:
            signed = -amount
        dest = r[11] or ""
        out.append(
            {
                "id": str(trans_id),
                "date": date_s,
                "status": r[2] or "",
                "type": code,
                "account": dest if code == "Transfer" else acct["name"],
                "payee": "" if code == "Transfer" else payee,
                "category": cat,
                "subcategory": sub,
                "amount": f"{signed:.2f}",
                "currency": symbol,
                "number": r[8] or "",
                "notes": r[9] or "",
                "tags": ";".join(tag_map.get(trans_id, [])),
                "withdrawal": f"{amount:.2f}" if code == "Withdrawal" else "",
                "deposit": f"{amount:.2f}" if code == "Deposit" else "",
                "balance": "",
            }
        )
    return acct, out


def export_file(
    engine: Engine,
    *,
    fmt: str,
    account_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
    fields: object = None,
    delimiter: str = ",",
    titles: bool = True,
    date_format: str = "YYYY-MM-DD",
) -> tuple[bytes, str, str]:
    fmt = (fmt or "csv").lower()
    if fmt not in ("csv", "qif", "xml"):
        raise IoError("format must be csv, qif or xml")
    field_list = parse_fields(fields) if fmt != "qif" else list(MMEX_FORMAT)
    acct, rows = _export_rows(engine, account_id, date_from=date_from, date_to=date_to)
    py_fmt = DATE_FORMATS.get(date_format, "%Y-%m-%d")
    for row in rows:
        try:
            row["date"] = datetime.strptime(row["date"], "%Y-%m-%d").strftime(py_fmt)
        except ValueError:
            pass
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", acct["name"])[:40]
    if fmt == "csv":
        delim = "\t" if delimiter in ("\\t", "\t") else (delimiter or ",")
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=delim)
        if titles:
            writer.writerow(field_list)
        for row in rows:
            writer.writerow([row.get(k, "") if k != "skip" else "" for k in field_list])
        payload = buf.getvalue().encode("utf-8")
        return payload, f"{safe}.csv", "text/csv; charset=utf-8"
    if fmt == "qif":
        lines = ["!Type:Bank"]
        for row in rows:
            lines.append("D" + row["date"])
            lines.append("T" + row["amount"])
            if row["payee"]:
                lines.append("P" + row["payee"])
            if row["type"] == "Transfer" and row["account"]:
                lines.append("L[" + row["account"] + "]")
            elif row["category"]:
                path = row["category"]
                if row["subcategory"]:
                    path = path + ":" + row["subcategory"]
                lines.append("L" + path)
            if row["notes"]:
                lines.append("M" + row["notes"].replace("\n", " "))
            if row["number"]:
                lines.append("N" + row["number"])
            if row["status"] == "R":
                lines.append("C*")
            elif row["status"] == "V":
                lines.append("CV")
            lines.append("^")
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        return payload, f"{safe}.qif", "application/x-qif"
    workbook = ET.Element("Workbook", {"xmlns": SS_NS})
    sheet = ET.SubElement(workbook, "Worksheet", {"Name": "MMEX"})
    table = ET.SubElement(sheet, "Table")
    if titles:
        row_el = ET.SubElement(table, "Row")
        for key in field_list:
            cell = ET.SubElement(row_el, "Cell")
            data_el = ET.SubElement(cell, "Data", {"Type": "String"})
            data_el.text = key
    for row in rows:
        row_el = ET.SubElement(table, "Row")
        for key in field_list:
            cell = ET.SubElement(row_el, "Cell")
            data_el = ET.SubElement(cell, "Data", {"Type": "String"})
            data_el.text = "" if key == "skip" else (row.get(key) or "")
    xml = ET.tostring(workbook, encoding="unicode")
    payload = ('<?xml version="1.0" encoding="utf-8"?>\n' + xml).encode("utf-8")
    return payload, f"{safe}.xml", "application/xml; charset=utf-8"
