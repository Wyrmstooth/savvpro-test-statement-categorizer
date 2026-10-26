import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "test.db"))) as test_client:
        yield test_client


def upload(client, text, filename="test.csv", **params):
    return client.post("/api/statements", params=params, files={"file": (filename, text, "text/csv")})


def workspace(client, **params):
    response = client.get("/api/workspace", params=params)
    assert response.status_code == 200
    return response.json()


def review_payload(row, **overrides):
    return {"category": "office", "flow": "expense", "version": row["version"], **overrides}


def test_end_to_end_demo_review_persistence_and_export(client):
    response = client.post("/api/demo")
    assert response.status_code == 201
    state = workspace(client, statement_id=response.json()["statement_id"])
    assert len(state["transactions"]) == 36
    summary = state["summary"]
    assert summary["cash_in_minor"] - summary["cash_out_minor"] == summary["net_movement_minor"]
    assert sum(c["net_minor"] for c in summary["categories"]) == summary["net_movement_minor"]
    row = next(t for t in state["transactions"] if "AMAZON" in t["description"])
    result = client.patch(f"/api/transactions/{row['id']}", json=review_payload(row, remember=True))
    assert result.status_code == 200
    assert not result.json()["needs_review"]
    fresh = workspace(client)
    assert fresh["summary"]["review_count"] == summary["review_count"] - 1
    assert len(fresh["rules"]) == 1
    history = client.get(f"/api/transactions/{row['id']}/history").json()
    assert history[0]["before"]["category"] == "uncategorized"
    assert history[0]["after"]["category"] == "office"
    exported = client.get("/api/export")
    assert exported.status_code == 200
    assert len(list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))) == 36


def test_repeated_file_is_not_counted_twice(client):
    first = client.post("/api/demo")
    second = client.post("/api/demo")
    assert second.status_code == 409
    assert second.json()["detail"]["statement_id"] == first.json()["statement_id"]
    assert workspace(client)["summary"]["total"] == 36


def test_possible_duplicate_requires_review_and_can_be_excluded(client):
    text = "Date,Description,Amount\n2026-10-01,FIGMA,-15\n2026-10-01,FIGMA,-15"
    assert upload(client, text).status_code == 201
    state = workspace(client)
    duplicate = next(t for t in state["transactions"] if t["duplicate"])
    assert duplicate["needs_review"]
    response = client.patch(
        f"/api/transactions/{duplicate['id']}",
        json=review_payload(
            duplicate,
            category="software",
            included=False,
        ),
    )
    assert response.status_code == 200
    assert workspace(client)["summary"]["confirmed"]["spending_minor"] == 1500
    assert workspace(client)["summary"]["excluded_count"] == 1


def test_optimistic_concurrency_rejects_stale_edits(client):
    client.post("/api/demo")
    row = workspace(client)["transactions"][0]
    payload = review_payload(row, category="transfer", flow="transfer")
    assert client.patch(f"/api/transactions/{row['id']}", json=payload).status_code == 200
    assert client.patch(f"/api/transactions/{row['id']}", json=payload).status_code == 409


def test_invalid_batch_rolls_back_every_edit(client):
    client.post("/api/demo")
    rows = workspace(client)["transactions"][:2]
    result = client.post(
        "/api/review-batch",
        json={
            "category": "office",
            "items": [
                {"id": rows[0]["id"], "version": rows[0]["version"]},
                {"id": rows[1]["id"], "version": 999},
            ],
        },
    )
    assert result.status_code == 409
    assert workspace(client)["transactions"][0]["version"] == rows[0]["version"]


def test_batch_review_updates_all_selected_rows(client):
    upload(client, "Date,Description,Amount\n2026-01-01,MYSTERY A,-1\n2026-01-02,MYSTERY B,-2")
    rows = workspace(client)["transactions"]
    result = client.post(
        "/api/review-batch",
        json={"category": "office", "items": [{"id": row["id"], "version": row["version"]} for row in rows]},
    )
    assert result.status_code == 200
    assert workspace(client)["summary"]["review_count"] == 0


def test_rules_apply_to_future_imports_and_only_exact_merchant(client):
    upload(client, "Date,Description,Amount\n2026-01-01,MYSTERY 54,-1")
    row = workspace(client)["transactions"][0]
    client.patch(f"/api/transactions/{row['id']}", json=review_payload(row, remember=True))
    upload(client, "Date,Description,Amount\n2026-02-01,MYSTERY 54,-2\n2026-02-01,MYSTERY 55,-2")
    rows = workspace(client)["transactions"]
    assert (
        next(r for r in rows if r["date"] == "2026-02-01" and r["merchant_key"] == "MYSTERY 54")["source"]
        == "rule"
    )
    assert next(r for r in rows if r["merchant_key"] == "MYSTERY 55")["needs_review"]
    rule_id = workspace(client)["rules"][0]["id"]
    assert client.delete(f"/api/rules/{rule_id}").status_code == 204
    assert workspace(client)["rules"] == []


def test_bad_import_is_atomic_and_actionable(client):
    result = upload(client, "Date,Description,Amount\n2026-01-01,ADOBE,-1\nBAD,FIGMA,-2")
    assert result.status_code == 422
    assert "Row 3" in result.json()["detail"]
    assert workspace(client)["statements"] == []


def test_currency_scopes_never_combine(client):
    upload(client, "Date,Description,Amount\n2026-01-01,ADOBE,-1", currency="USD")
    upload(client, "Date,Description,Amount\n2026-01-01,FIGMA,-20", currency="GBP")
    assert workspace(client, currency="USD")["summary"]["provisional"]["spending_minor"] == 100
    assert workspace(client, currency="GBP")["summary"]["provisional"]["spending_minor"] == 2000


def test_refunds_reduce_spending_and_never_inflate_income(client):
    upload(client, "Date,Description,Amount\n2026-01-01,ADOBE,-50\n2026-01-02,ADOBE REFUND,10")
    summary = workspace(client)["summary"]
    assert summary["confirmed"]["spending_minor"] == 4000
    assert summary["confirmed"]["income_minor"] == 0
    assert summary["refund_minor"] == 1000


def test_csv_export_escapes_spreadsheet_formulas(client):
    upload(client, 'Date,Description,Amount\n2026-01-01,=HYPERLINK("bad"),-10')
    exported = client.get("/api/export").content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(exported)))
    assert rows[0]["Description"].startswith("'=")
    assert rows[0]["Amount"] == "-10.00"


@pytest.mark.parametrize("filename,status", [("bad.exe", 415), ("empty.csv", 422)])
def test_invalid_file_types_and_empty_files(client, filename, status):
    assert upload(client, b"", filename).status_code == status


def test_cross_origin_mutation_rejected(client):
    assert client.post("/api/demo", headers={"Origin": "https://untrusted.example"}).status_code == 403


def test_invalid_review_does_not_create_audit_or_rule(client):
    client.post("/api/demo")
    row = next(t for t in workspace(client)["transactions"] if t["amount_minor"] < 0)
    response = client.patch(
        f"/api/transactions/{row['id']}",
        json=review_payload(
            row,
            category="income",
            flow="income",
            remember=True,
        ),
    )
    assert response.status_code == 422
    assert workspace(client)["rules"] == []
    assert client.get(f"/api/transactions/{row['id']}/history").json() == []


def test_confirmed_export_omits_unresolved_rows(client):
    client.post("/api/demo")
    state = workspace(client)
    exported = client.get("/api/export?confirmed_only=true").content.decode("utf-8-sig")
    assert len(list(csv.DictReader(io.StringIO(exported)))) == state["summary"]["ready_count"]


def test_summary_export_includes_review_counts(client):
    client.post("/api/demo")
    exported = client.get("/api/export?kind=summary").content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(exported)))
    assert len(rows) == 11
    assert sum(int(row["Needs review"]) for row in rows) == workspace(client)["summary"]["review_count"]


def test_refund_history_linking_is_currency_date_and_capacity_scoped(client):
    upload(client, "Date,Description,Amount\n2026-01-01,PAPER AND INK,-10")
    row = workspace(client)["transactions"][0]
    client.patch(f"/api/transactions/{row['id']}", json=review_payload(row))
    upload(client, "Date,Description,Amount\n2026-01-03,PAPER AND INK REFUND,4")
    linked = workspace(client)["transactions"][0]
    assert linked["source"] == "context"
    assert linked["category"] == "office"
    upload(client, "Date,Description,Amount\n2026-01-04,PAPER AND INK REFUND,7")
    assert workspace(client)["transactions"][0]["needs_review"]
    upload(client, "Date,Description,Amount\n2025-12-01,PAPER AND INK REFUND,1")
    assert next(t for t in workspace(client)["transactions"] if t["date"] == "2025-12-01")["needs_review"]
    upload(client, "Date,Description,Amount\n2026-02-01,PAPER AND INK REFUND,1", currency="GBP")
    assert workspace(client, currency="GBP")["transactions"][0]["needs_review"]


def test_untrusted_host_cannot_rebind_local_workspace(client):
    assert client.get("/api/workspace", headers={"Host": "untrusted.example"}).status_code == 400


def test_statement_removal_cascades_history_and_allows_reimport(client):
    response = client.post("/api/demo")
    statement_id = response.json()["statement_id"]
    row = workspace(client)["transactions"][0]
    client.patch(
        f"/api/transactions/{row['id']}", json=review_payload(row, category="transfer", flow="transfer")
    )
    assert client.delete(f"/api/statements/{statement_id}").status_code == 204
    assert workspace(client)["transactions"] == []
    assert client.get(f"/api/transactions/{row['id']}/history").status_code == 404
    assert client.post("/api/demo").status_code == 201


def test_aggregate_money_stays_exact_for_browser_clients(client):
    text = "Date,Description,Amount\n" + "\n".join(
        f"2026-01-01,ADOBE REF {index},-999999999999.99" for index in range(91)
    )
    response = upload(client, text)
    assert response.status_code == 422
    assert "currency range" in response.json()["detail"]
    assert workspace(client)["statements"] == []
