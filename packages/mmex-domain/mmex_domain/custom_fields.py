"""CUSTOMFIELD_V1 / CUSTOMFIELDDATA_V1 (desktop Model_CustomField).

PROPERTIES is a JSON object with optional Tooltip, RegEx, Autocomplete,
Default, Choice (array), DigitScale, UDFC (UDFC01–UDFC05).
Boolean values store TRUE/FALSE. MultiChoice stores semicolon-separated
choices. Empty content deletes the data row.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from mmex_domain.attachments import REF_TYPES

FIELD_TYPES = (
    "String",
    "Integer",
    "Decimal",
    "Boolean",
    "Date",
    "Time",
    "SingleChoice",
    "MultiChoice",
)
UDFC_SLOTS = ("", "UDFC01", "UDFC02", "UDFC03", "UDFC04", "UDFC05")


class CustomFieldError(ValueError):
    """Invalid custom field definition or value."""


def _next_id(conn: Connection, table: str, column: str) -> int:
    now_based = int(time.time() * 1000) * 1000
    max_id = int(conn.execute(text(f"SELECT MAX({column}) FROM {table}")).scalar() or 0)
    return max(now_based, max_id + 1)


def meta() -> dict[str, Any]:
    return {
        "ref_types": list(REF_TYPES),
        "field_types": list(FIELD_TYPES),
        "udfc": [s for s in UDFC_SLOTS if s],
    }


def _ref_type(value: object) -> str:
    raw = str(value or "").strip()
    for item in REF_TYPES:
        if item.lower() == raw.lower():
            return item
    raise CustomFieldError("invalid ref_type")


def _field_type(value: object) -> str:
    raw = str(value or "").strip()
    for item in FIELD_TYPES:
        if item.lower() == raw.lower():
            return item
    raise CustomFieldError("invalid field type")


def parse_properties(raw: object) -> dict[str, Any]:
    text_val = str(raw or "").strip()
    if not text_val:
        return {
            "tooltip": "",
            "regex": "",
            "autocomplete": False,
            "default": "",
            "choices": [],
            "digit_scale": 0,
            "udfc": "",
        }
    try:
        data = json.loads(text_val)
    except json.JSONDecodeError as exc:
        raise CustomFieldError("invalid properties JSON") from exc
    if not isinstance(data, dict):
        raise CustomFieldError("invalid properties JSON")
    choices = data.get("Choice") or []
    if isinstance(choices, str):
        choices = [c for c in choices.split(";") if c != ""]
    else:
        choices = [str(c) for c in choices]
    udfc = str(data.get("UDFC") or "")
    if udfc not in UDFC_SLOTS:
        udfc = ""
    scale = data.get("DigitScale") or 0
    try:
        scale = int(scale)
    except (TypeError, ValueError):
        scale = 0
    return {
        "tooltip": str(data.get("Tooltip") or ""),
        "regex": str(data.get("RegEx") or ""),
        "autocomplete": bool(data.get("Autocomplete")),
        "default": str(data.get("Default") or ""),
        "choices": choices,
        "digit_scale": max(0, min(scale, 20)),
        "udfc": udfc,
    }


def format_properties(props: dict[str, Any]) -> str:
    out: dict[str, Any] = {}
    tooltip = str(props.get("tooltip") or "").strip()
    regex = str(props.get("regex") or "").strip()
    default = str(props.get("default") or "")
    choices = props.get("choices") or []
    if isinstance(choices, str):
        choices = [c.strip() for c in choices.split(";") if c.strip()]
    else:
        choices = [str(c).strip() for c in choices if str(c).strip()]
    scale = int(props.get("digit_scale") or 0)
    udfc = str(props.get("udfc") or "")
    if udfc not in UDFC_SLOTS:
        udfc = ""
    if tooltip:
        out["Tooltip"] = tooltip
    if regex:
        try:
            re.compile(regex)
        except re.error as exc:
            raise CustomFieldError("invalid regex") from exc
        out["RegEx"] = regex
    if props.get("autocomplete"):
        out["Autocomplete"] = True
    if default:
        out["Default"] = default
    if choices:
        out["Choice"] = choices
    if scale:
        out["DigitScale"] = max(0, min(scale, 20))
    if udfc:
        out["UDFC"] = udfc
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def _serialize_field(row: Any, *, used: int = 0) -> dict[str, Any]:
    props = parse_properties(row[4])
    return {
        "field_id": int(row[0]),
        "ref_type": row[1],
        "name": row[2] or "",
        "type": row[3],
        "properties": props,
        "used_count": used,
    }


def list_fields(engine: Engine, ref_type: str | None = None) -> dict[str, Any]:
    where = ""
    params: dict[str, Any] = {}
    if ref_type:
        where = "WHERE f.REFTYPE = :rt"
        params["rt"] = _ref_type(ref_type)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT f.FIELDID, f.REFTYPE, f.DESCRIPTION, f.TYPE, f.PROPERTIES,
                       (SELECT COUNT(*) FROM CUSTOMFIELDDATA_V1 d WHERE d.FIELDID = f.FIELDID)
                  FROM CUSTOMFIELD_V1 f
                  {where}
                 ORDER BY f.REFTYPE, f.DESCRIPTION COLLATE NOCASE
                """
            ),
            params,
        ).fetchall()
    return {
        "fields": [_serialize_field(r, used=int(r[5] or 0)) for r in rows],
        "meta": meta(),
    }


def get_field(engine: Engine, field_id: int) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT f.FIELDID, f.REFTYPE, f.DESCRIPTION, f.TYPE, f.PROPERTIES,
                       (SELECT COUNT(*) FROM CUSTOMFIELDDATA_V1 d WHERE d.FIELDID = f.FIELDID)
                  FROM CUSTOMFIELD_V1 f WHERE f.FIELDID = :id
                """
            ),
            {"id": field_id},
        ).fetchone()
    if row is None:
        raise CustomFieldError("unknown field")
    return _serialize_field(row, used=int(row[5] or 0))


def _assert_udfc(conn: Connection, ref_type: str, udfc: str, field_id: int | None) -> None:
    if not udfc:
        return
    row = conn.execute(
        text(
            """
            SELECT FIELDID, PROPERTIES FROM CUSTOMFIELD_V1
             WHERE REFTYPE = :rt AND FIELDID != :id
            """
        ),
        {"rt": ref_type, "id": field_id or 0},
    ).fetchall()
    for other in row:
        other_udfc = parse_properties(other[1])["udfc"]
        if other_udfc == udfc:
            raise CustomFieldError(f"{udfc} already assigned")


def create_field(engine: Engine, data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not name:
        raise CustomFieldError("name is required")
    ref_type = _ref_type(data.get("ref_type"))
    field_type = _field_type(data.get("type"))
    props_in = data.get("properties") or {}
    if field_type in ("SingleChoice", "MultiChoice"):
        choices = props_in.get("choices") or []
        if isinstance(choices, str):
            choices = [c for c in choices.split(";") if c.strip()]
        if not choices:
            raise CustomFieldError("choices are required")
    encoded = format_properties(props_in)
    parsed = parse_properties(encoded)
    with engine.begin() as conn:
        _assert_udfc(conn, ref_type, parsed["udfc"], None)
        field_id = _next_id(conn, "CUSTOMFIELD_V1", "FIELDID")
        conn.execute(
            text(
                """
                INSERT INTO CUSTOMFIELD_V1 (FIELDID, REFTYPE, DESCRIPTION, TYPE, PROPERTIES)
                VALUES (:id, :rt, :name, :typ, :props)
                """
            ),
            {
                "id": field_id,
                "rt": ref_type,
                "name": name,
                "typ": field_type,
                "props": encoded,
            },
        )
    return get_field(engine, field_id)


def update_field(engine: Engine, field_id: int, data: dict[str, Any]) -> dict[str, Any]:
    current = get_field(engine, field_id)
    name = str(data.get("name") if data.get("name") is not None else current["name"]).strip()
    if not name:
        raise CustomFieldError("name is required")
    ref_type = _ref_type(data.get("ref_type") if "ref_type" in data else current["ref_type"])
    field_type = _field_type(data.get("type") if "type" in data else current["type"])
    props_in = data.get("properties") if "properties" in data else current["properties"]
    if field_type in ("SingleChoice", "MultiChoice"):
        choices = (props_in or {}).get("choices") or []
        if isinstance(choices, str):
            choices = [c for c in choices.split(";") if c.strip()]
        if not choices:
            raise CustomFieldError("choices are required")
    encoded = format_properties(props_in or {})
    parsed = parse_properties(encoded)
    with engine.begin() as conn:
        if field_type != current["type"] and current["used_count"]:
            raise CustomFieldError("field still has values")
        _assert_udfc(conn, ref_type, parsed["udfc"], field_id)
        conn.execute(
            text(
                """
                UPDATE CUSTOMFIELD_V1 SET REFTYPE=:rt, DESCRIPTION=:name, TYPE=:typ,
                       PROPERTIES=:props
                 WHERE FIELDID=:id
                """
            ),
            {
                "rt": ref_type,
                "name": name,
                "typ": field_type,
                "props": encoded,
                "id": field_id,
            },
        )
    return get_field(engine, field_id)


def delete_field(engine: Engine, field_id: int) -> None:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT FIELDID FROM CUSTOMFIELD_V1 WHERE FIELDID = :id"),
            {"id": field_id},
        ).fetchone()
        if row is None:
            raise CustomFieldError("unknown field")
        conn.execute(
            text("DELETE FROM CUSTOMFIELDDATA_V1 WHERE FIELDID = :id"),
            {"id": field_id},
        )
        conn.execute(
            text("DELETE FROM CUSTOMFIELD_V1 WHERE FIELDID = :id"),
            {"id": field_id},
        )


def _resolve_default(field_type: str, default: str) -> str:
    if default.strip().lower() == "now":
        if field_type == "Date":
            return date.today().isoformat()
        if field_type == "Time":
            return datetime.now().strftime("%H:%M:%S")
    return default


def values_for(engine: Engine, ref_type: str, ref_id: int) -> dict[str, Any]:
    rt = _ref_type(ref_type)
    if ref_id <= 0:
        raise CustomFieldError("ref_id is required")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT f.FIELDID, f.REFTYPE, f.DESCRIPTION, f.TYPE, f.PROPERTIES,
                       d.CONTENT, d.FIELDATADID
                  FROM CUSTOMFIELD_V1 f
                  LEFT JOIN CUSTOMFIELDDATA_V1 d
                    ON d.FIELDID = f.FIELDID AND d.REFID = :rid
                 WHERE f.REFTYPE = :rt
                 ORDER BY f.DESCRIPTION COLLATE NOCASE
                """
            ),
            {"rt": rt, "rid": ref_id},
        ).fetchall()
    values = []
    for r in rows:
        field = _serialize_field(r)
        content = r[5]
        values.append(
            {
                **field,
                "content": content,
                "default": _resolve_default(field["type"], field["properties"]["default"]),
                "field_data_id": int(r[6]) if r[6] is not None else None,
            }
        )
    return {"ref_type": rt, "ref_id": ref_id, "values": values}


def _normalize_content(field: dict[str, Any], raw: object) -> str:
    content = "" if raw is None else str(raw).strip()
    if not content:
        return ""
    ftype = field["type"]
    props = field["properties"]
    if ftype == "Boolean":
        low = content.lower()
        if low in ("1", "true", "yes", "oui"):
            content = "TRUE"
        elif low in ("0", "false", "no", "non"):
            content = "FALSE"
        else:
            raise CustomFieldError(f"{field['name']}: invalid boolean")
    elif ftype == "Integer":
        try:
            content = str(int(Decimal(content)))
        except (InvalidOperation, ValueError) as exc:
            raise CustomFieldError(f"{field['name']}: invalid integer") from exc
    elif ftype == "Decimal":
        try:
            value = Decimal(content)
        except InvalidOperation as exc:
            raise CustomFieldError(f"{field['name']}: invalid decimal") from exc
        scale = int(props.get("digit_scale") or 0)
        if scale > 0:
            q = Decimal("1").scaleb(-scale)
            content = str(value.quantize(q))
        else:
            content = str(value)
    elif ftype == "Date":
        try:
            date.fromisoformat(content[:10])
        except ValueError as exc:
            raise CustomFieldError(f"{field['name']}: invalid date") from exc
        content = content[:10]
    elif ftype == "Time":
        parts = content.split(":")
        if len(parts) < 2:
            raise CustomFieldError(f"{field['name']}: invalid time")
        try:
            hour, minute = int(parts[0]), int(parts[1])
            second = int(parts[2][:2]) if len(parts) > 2 else 0
        except ValueError as exc:
            raise CustomFieldError(f"{field['name']}: invalid time") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
            raise CustomFieldError(f"{field['name']}: invalid time")
        content = f"{hour:02d}:{minute:02d}:{second:02d}"
    elif ftype == "SingleChoice":
        if content not in props["choices"]:
            raise CustomFieldError(f"{field['name']}: invalid choice")
    elif ftype == "MultiChoice":
        selected = [c for c in content.split(";") if c]
        for item in selected:
            if item not in props["choices"]:
                raise CustomFieldError(f"{field['name']}: invalid choice")
        content = ";".join(selected)
    regex = props.get("regex") or ""
    if regex and not re.search(regex, content):
        raise CustomFieldError(f"{field['name']}: value does not match regex")
    return content


def save_values(
    engine: Engine, ref_type: str, ref_id: int, values: list[dict[str, Any]]
) -> dict[str, Any]:
    rt = _ref_type(ref_type)
    if ref_id <= 0:
        raise CustomFieldError("ref_id is required")
    incoming = {int(v["field_id"]): v.get("content") for v in values}
    with engine.begin() as conn:
        fields = conn.execute(
            text(
                """
                SELECT FIELDID, REFTYPE, DESCRIPTION, TYPE, PROPERTIES
                  FROM CUSTOMFIELD_V1 WHERE REFTYPE = :rt
                """
            ),
            {"rt": rt},
        ).fetchall()
        by_id = {int(r[0]): _serialize_field(r) for r in fields}
        for field_id, raw in incoming.items():
            field = by_id.get(field_id)
            if field is None:
                raise CustomFieldError("unknown field")
            content = _normalize_content(field, raw)
            existing = conn.execute(
                text(
                    "SELECT FIELDATADID FROM CUSTOMFIELDDATA_V1 "
                    "WHERE FIELDID = :fid AND REFID = :rid"
                ),
                {"fid": field_id, "rid": ref_id},
            ).fetchone()
            if not content:
                if existing:
                    conn.execute(
                        text("DELETE FROM CUSTOMFIELDDATA_V1 WHERE FIELDATADID = :id"),
                        {"id": int(existing[0])},
                    )
                continue
            if existing:
                conn.execute(
                    text(
                        "UPDATE CUSTOMFIELDDATA_V1 SET CONTENT = :c WHERE FIELDATADID = :id"
                    ),
                    {"c": content, "id": int(existing[0])},
                )
            else:
                data_id = _next_id(conn, "CUSTOMFIELDDATA_V1", "FIELDATADID")
                conn.execute(
                    text(
                        """
                        INSERT INTO CUSTOMFIELDDATA_V1 (FIELDATADID, FIELDID, REFID, CONTENT)
                        VALUES (:id, :fid, :rid, :c)
                        """
                    ),
                    {"id": data_id, "fid": field_id, "rid": ref_id, "c": content},
                )
    return values_for(engine, rt, ref_id)
