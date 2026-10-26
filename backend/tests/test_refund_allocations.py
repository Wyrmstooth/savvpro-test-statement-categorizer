import pytest
from fastapi.testclient import TestClient

from app.engine import merchant_key
from app.main import create_app
from app.storage import connect, initialize


@pytest.fixture
def setup(tmp_path):
    path = str(tmp_path / "refunds.db")
    with TestClient(create_app(path)) as client:
        yield client, path


def upload(client, description, amount, day, currency="USD"):
    data = f"Date,Description,Amount\n{day},{description},{amount}"
    response = client.post(
        "/api/statements", params={"currency": currency}, files={"file": ("fictional.csv", data.encode())}
    )
    assert response.status_code == 201, response.text
    statement_id = response.json()["statement_id"]
    state = client.get("/api/workspace", params={"statement_id": statement_id}).json()
    return state["transactions"][0]


def confirm(client, row, **values):
    body = {
        "category": "office",
        "flow": "expense" if row["amount_minor"] < 0 else "refund",
        "version": row["version"],
        **values,
    }
    response = client.patch(f"/api/transactions/{row['id']}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def rows(client, currency="USD"):
    return {
        r["id"]: r for r in client.get("/api/workspace", params={"currency": currency}).json()["transactions"]
    }


def allocations(path):
    with connect(path) as db:
        return [dict(r) for r in db.execute("SELECT * FROM refund_allocations")]


def test_unrelated_non_latin_merchants_cannot_share_refund_capacity(setup):
    client, path = setup
    purchase = upload(client, "\u66f8\u5e97", "-10", "2026-01-01")
    confirm(client, purchase)
    refund = upload(client, "\u9910\u9928 REFUND", "7", "2026-01-02")
    assert merchant_key(purchase["description"]) != merchant_key(refund["description"])
    assert refund["needs_review"]
    assert allocations(path) == []


def test_empty_symbol_only_keys_never_enable_automatic_refunds(setup):
    client, path = setup
    purchase = upload(client, "---", "-10", "2026-01-01")
    confirm(client, purchase)
    refund = upload(client, "*** REFUND", "7", "2026-01-02")
    assert purchase["merchant_key"] == refund["merchant_key"] == ""
    assert refund["needs_review"]
    assert allocations(path) == []


def test_same_non_latin_identity_can_match_and_learn_exactly(setup):
    client, _ = setup
    purchase = upload(client, "\u66f8\u5e97", "-10", "2026-01-01")
    confirm(client, purchase, remember=True)
    refund = upload(client, "\u66f8\u5e97 REFUND", "7", "2026-01-02")
    assert refund["source"] == "context" and not refund["needs_review"]
    other = upload(client, "\u9910\u9928", "-3", "2026-01-03")
    assert other["needs_review"] and other["source"] != "rule"


def test_backdated_refund_cannot_reuse_a_later_refunds_allocation(setup):
    client, path = setup
    confirm(client, upload(client, "PAPER AND INK", "-10", "2026-01-01"))
    first = upload(client, "PAPER AND INK REFUND", "7", "2026-01-03")
    backdated = upload(client, "PAPER AND INK REFUND", "7", "2026-01-02")
    assert not rows(client)[first["id"]]["needs_review"]
    assert backdated["needs_review"]
    assert sum(r["amount_minor"] for r in allocations(path)) == 700


def test_partial_refunds_fit_exactly_across_multiple_purchases(setup):
    client, path = setup
    for day, amount in [("2026-01-01", "-4.01"), ("2026-01-02", "-5.99")]:
        confirm(client, upload(client, "PAPER AND INK", amount, day))
    first = upload(client, "PAPER AND INK REFUND", "7", "2026-01-04")
    second = upload(client, "PAPER AND INK REFUND", "3", "2026-01-03")
    excess = upload(client, "PAPER AND INK REFUND", "0.01", "2026-01-05")
    assert not first["needs_review"] and not second["needs_review"]
    assert excess["needs_review"]
    assert sum(r["amount_minor"] for r in allocations(path)) == 1000


@pytest.mark.parametrize("change", ["delete", "exclude", "recategorize"])
def test_purchase_changes_revalidate_dependent_context_refunds(setup, change):
    client, path = setup
    purchase = confirm(client, upload(client, "PAPER AND INK", "-10", "2026-01-01"))
    refund = upload(client, "PAPER AND INK REFUND", "7", "2026-01-02")
    assert not refund["needs_review"]
    if change == "delete":
        assert client.delete(f"/api/statements/{purchase['statement_id']}").status_code == 204
    elif change == "exclude":
        confirm(client, purchase, included=False)
    else:
        confirm(client, purchase, category="software")
    after = rows(client)[refund["id"]]
    assert after["needs_review"]
    assert after["version"] > refund["version"]
    assert allocations(path) == []
    history = client.get(f"/api/transactions/{refund['id']}/history").json()
    assert history[0]["action"] == "refund_revalidation"
    assert not history[0]["before"]["needs_review"] and history[0]["after"]["needs_review"]


def test_explicit_refunds_reserve_capacity_before_automatic_inference(setup):
    client, path = setup
    confirm(client, upload(client, "PAPER AND INK", "-10", "2026-01-01"))
    manual = upload(client, "PAPER AND INK", "7", "2026-01-04")
    confirm(client, manual)
    candidate = upload(client, "PAPER AND INK REFUND", "7", "2026-01-02")
    assert candidate["needs_review"]
    assert sum(r["amount_minor"] for r in allocations(path)) == 700


def test_deleting_a_refund_releases_only_its_own_reservations(setup):
    client, path = setup
    confirm(client, upload(client, "PAPER AND INK", "-10", "2026-01-01"))
    first = upload(client, "PAPER AND INK REFUND", "7", "2026-01-03")
    assert client.delete(f"/api/statements/{first['statement_id']}").status_code == 204
    second = upload(client, "PAPER AND INK REFUND", "7", "2026-01-02")
    assert not second["needs_review"]
    assert {r["refund_id"] for r in allocations(path)} == {second["id"]}


def test_revalidation_is_idempotent_across_restarts(setup):
    client, path = setup
    confirm(client, upload(client, "PAPER AND INK", "-10", "2026-01-01"))
    refund = upload(client, "PAPER AND INK REFUND", "7", "2026-01-03")
    initialize(path)
    once = rows(client)[refund["id"]]
    initialize(path)
    twice = rows(client)[refund["id"]]
    assert once == twice
    assert sum(r["amount_minor"] for r in allocations(path)) == 700


def test_existing_oversubscribed_context_refunds_are_repaired_on_startup(setup):
    client, path = setup
    confirm(client, upload(client, "PAPER AND INK", "-10", "2026-01-01"))
    first = upload(client, "PAPER AND INK REFUND", "7", "2026-01-03")
    second = upload(client, "PAPER AND INK REFUND", "7", "2026-01-02")
    with connect(path) as db:
        db.execute(
            "UPDATE transactions SET category='office',source='context',needs_review=0 WHERE id=?",
            (second["id"],),
        )
    initialize(path)
    state = rows(client)
    assert not state[first["id"]]["needs_review"] and state[second["id"]]["needs_review"]
    assert sum(r["amount_minor"] for r in allocations(path)) == 700


def test_ambiguous_legacy_merchant_rules_are_retained_but_disabled(setup):
    client, path = setup
    row = confirm(client, upload(client, "SHOP\u66f8\u5e97", "-10", "2026-01-01"), remember=True)
    with connect(path) as db:
        db.execute("UPDATE transactions SET merchant_key='SHOP' WHERE id=?", (row["id"],))
        db.execute("UPDATE rules SET merchant_key='SHOP',identity_version=1")
    initialize(path)
    rule = client.get("/api/workspace").json()["rules"][0]
    assert rule["needs_confirmation"]
    initialize(path)
    assert client.get("/api/workspace").json()["rules"][0]["needs_confirmation"]
    unrelated = upload(client, "SHOP", "-5", "2026-01-03")
    assert unrelated["needs_review"] and unrelated["source"] != "rule"
    assert rows(client)[row["id"]]["category"] == "office"  # Human decisions survive migration.


def test_non_latin_continuation_does_not_create_a_false_ascii_brand_boundary(setup):
    client, _ = setup
    row = upload(client, "ADOBE\u66f8\u5e97", "-10", "2026-01-01")
    assert row["needs_review"]


def test_future_purchases_cannot_fund_a_backdated_refund(setup):
    client, _ = setup
    confirm(client, upload(client, "PAPER AND INK", "-10", "2026-01-01"))
    upload(client, "PAPER AND INK REFUND", "7", "2026-01-03")
    confirm(client, upload(client, "PAPER AND INK", "-10", "2026-01-04"))
    assert upload(client, "PAPER AND INK REFUND", "7", "2026-01-02")["needs_review"]


def test_excluded_refund_releases_capacity_and_stale_dependent_edits_fail(setup):
    client, _ = setup
    purchase = confirm(client, upload(client, "PAPER AND INK", "-10", "2026-01-01"))
    first = upload(client, "PAPER AND INK REFUND", "7", "2026-01-03")
    confirm(client, first, included=False)
    second = upload(client, "PAPER AND INK REFUND", "7", "2026-01-02")
    assert not second["needs_review"]
    confirm(client, purchase, included=False)
    stale = client.patch(
        f"/api/transactions/{second['id']}",
        json={
            "category": "office",
            "flow": "refund",
            "version": second["version"],
        },
    )
    assert stale.status_code == 409


def test_concurrent_refund_imports_cannot_double_reserve_one_purchase(setup):
    from concurrent.futures import ThreadPoolExecutor

    client, path = setup
    confirm(client, upload(client, "PAPER AND INK", "-10", "2026-01-01"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda day: upload(client, "PAPER AND INK REFUND", "7", day), ["2026-01-02", "2026-01-03"]
            )
        )
    assert sum(not row["needs_review"] for row in results) == 1
    assert sum(row["amount_minor"] for row in allocations(path)) == 700


def test_old_rules_schema_upgrades_without_dropping_data(tmp_path):
    import sqlite3

    path = str(tmp_path / "legacy.db")
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE rules (id TEXT PRIMARY KEY,merchant_key TEXT,direction TEXT,category TEXT,"
            "created_at TEXT,UNIQUE(merchant_key,direction))"
        )
        db.execute(
            "INSERT INTO rules VALUES (?,?,?,?,?)",
            ("legacy", "PAPER AND INK", "expense", "office", "2026-01-01"),
        )
    initialize(path)
    with connect(path) as db:
        row = dict(db.execute("SELECT * FROM rules").fetchone())
        assert row["id"] == "legacy" and row["identity_version"] == 2


def test_old_collapsed_unicode_matches_are_repaired_without_changing_manual_decisions(setup):
    client, path = setup
    purchase = confirm(client, upload(client, "\u66f8\u5e97", "-10", "2026-01-01"))
    refund = upload(client, "\u9910\u9928 REFUND", "7", "2026-01-02")
    with connect(path) as db:
        db.execute(
            "UPDATE transactions SET merchant_key='' WHERE id IN (?,?)", (purchase["id"], refund["id"])
        )
        db.execute(
            "UPDATE transactions SET source='context',category='office',needs_review=0 WHERE id=?",
            (refund["id"],),
        )
    initialize(path)
    current = rows(client)
    assert current[purchase["id"]]["category"] == "office" and not current[purchase["id"]]["needs_review"]
    assert current[refund["id"]]["needs_review"]
    assert allocations(path) == []


def test_old_rule_decisions_with_ambiguous_identities_return_to_review(setup):
    client, path = setup
    original = confirm(client, upload(client, "SHOP\u66f8\u5e97", "-10", "2026-01-01"), remember=True)
    wrong = upload(client, "SHOP", "-3", "2026-01-02")
    with connect(path) as db:
        db.execute("UPDATE transactions SET merchant_key='SHOP' WHERE id=?", (original["id"],))
        db.execute(
            "UPDATE transactions SET source='rule',category='office',needs_review=0 WHERE id=?",
            (wrong["id"],),
        )
        db.execute("UPDATE rules SET merchant_key='SHOP',identity_version=1")
    initialize(path)
    assert rows(client)[wrong["id"]]["needs_review"]
    assert not rows(client)[original["id"]]["needs_review"]
