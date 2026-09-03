from __future__ import annotations

from fastapi.testclient import TestClient

from mmex_web_api.config import Settings
from tests.test_transactions import _seed


def test_field_crud_values_regex_and_choices(
    authed_client: TestClient, mmex_settings: Settings
) -> None:
    _seed(mmex_settings)
    created_txn = authed_client.post(
        "/api/transactions",
        json={
            "account_id": 1,
            "trans_code": "Withdrawal",
            "trans_amount": "3.00",
            "trans_date": "2026-03-01",
            "payee_id": 10,
            "status": "",
        },
    )
    assert created_txn.status_code == 200, created_txn.text
    trans_id = created_txn.json()["trans_id"]

    meta = authed_client.get("/api/custom-fields/meta")
    assert meta.status_code == 200
    assert "Transaction" in meta.json()["ref_types"]
    assert "MultiChoice" in meta.json()["field_types"]

    method = authed_client.post(
        "/api/custom-fields",
        json={
            "name": "Méthode",
            "ref_type": "Transaction",
            "type": "SingleChoice",
            "properties": {
                "tooltip": "Paiement",
                "choices": ["Carte", "Espèces", "Virement"],
                "udfc": "UDFC01",
            },
        },
    )
    assert method.status_code == 200, method.text
    method_id = method.json()["field_id"]
    assert method.json()["properties"]["choices"] == ["Carte", "Espèces", "Virement"]
    assert method.json()["properties"]["udfc"] == "UDFC01"

    dup_udfc = authed_client.post(
        "/api/custom-fields",
        json={
            "name": "Autre",
            "ref_type": "Transaction",
            "type": "String",
            "properties": {"udfc": "UDFC01"},
        },
    )
    assert dup_udfc.status_code == 409

    ref = authed_client.post(
        "/api/custom-fields",
        json={
            "name": "Référence",
            "ref_type": "Transaction",
            "type": "String",
            "properties": {"regex": r"^PRAT-\d{4}$", "default": "PRAT-0000"},
        },
    )
    assert ref.status_code == 200, ref.text
    ref_id = ref.json()["field_id"]

    tags = authed_client.post(
        "/api/custom-fields",
        json={
            "name": "Flags",
            "ref_type": "Transaction",
            "type": "MultiChoice",
            "properties": {"choices": ["A", "B", "C"]},
        },
    )
    flag_id = tags.json()["field_id"]

    boolf = authed_client.post(
        "/api/custom-fields",
        json={"name": "Garantie", "ref_type": "Transaction", "type": "Boolean"},
    )
    bool_id = boolf.json()["field_id"]

    bad_choice = authed_client.put(
        "/api/custom-fields/values",
        json={
            "ref_type": "Transaction",
            "ref_id": trans_id,
            "values": [{"field_id": method_id, "content": "Chèque"}],
        },
    )
    assert bad_choice.status_code == 400

    bad_regex = authed_client.put(
        "/api/custom-fields/values",
        json={
            "ref_type": "Transaction",
            "ref_id": trans_id,
            "values": [{"field_id": ref_id, "content": "nope"}],
        },
    )
    assert bad_regex.status_code == 400

    saved = authed_client.put(
        "/api/custom-fields/values",
        json={
            "ref_type": "Transaction",
            "ref_id": trans_id,
            "values": [
                {"field_id": method_id, "content": "Carte"},
                {"field_id": ref_id, "content": "PRAT-2026"},
                {"field_id": flag_id, "content": "A;C"},
                {"field_id": bool_id, "content": "true"},
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    by_name = {v["name"]: v for v in saved.json()["values"]}
    assert by_name["Méthode"]["content"] == "Carte"
    assert by_name["Référence"]["content"] == "PRAT-2026"
    assert by_name["Flags"]["content"] == "A;C"
    assert by_name["Garantie"]["content"] == "TRUE"

    listed = authed_client.get("/api/custom-fields", params={"ref_type": "Transaction"})
    assert listed.status_code == 200
    used = next(f for f in listed.json()["fields"] if f["field_id"] == method_id)
    assert used["used_count"] == 1

    type_change = authed_client.put(
        f"/api/custom-fields/{method_id}",
        json={"type": "String"},
    )
    assert type_change.status_code == 409

    cleared = authed_client.put(
        "/api/custom-fields/values",
        json={
            "ref_type": "Transaction",
            "ref_id": trans_id,
            "values": [{"field_id": method_id, "content": ""}],
        },
    )
    assert cleared.status_code == 200
    again = next(v for v in cleared.json()["values"] if v["field_id"] == method_id)
    assert again["content"] is None

    deleted = authed_client.delete(f"/api/custom-fields/{ref_id}")
    assert deleted.status_code == 200
    remaining = authed_client.get("/api/custom-fields/values", params={"ref_type": "Transaction", "ref_id": trans_id})
    names = {v["name"] for v in remaining.json()["values"]}
    assert "Référence" not in names

    for fid in (method_id, flag_id, bool_id):
        assert authed_client.delete(f"/api/custom-fields/{fid}").status_code == 200

    authed_client.post(f"/api/transactions/{trans_id}/delete")
