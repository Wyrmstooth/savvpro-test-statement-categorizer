"""Transactional refund capacity reservations and dependency revalidation.

Existing accepted refunds reserve capacity before newly imported backdated refunds.
Only automatically inferred matches are invalidated; explicit user decisions remain authoritative.
"""

import json
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from app.engine import ENGINE_VERSION, EXPENSE_CATEGORIES, Decision, merchant_key, resolve_refund
from app.storage import transaction_dict


def timestamp():
    return datetime.now(UTC).isoformat()


def audit(db, before, after, action):
    db.execute(
        "INSERT INTO audit VALUES (?,?,?,?,?,?)",
        (
            uuid4().hex,
            before["id"],
            action,
            json.dumps(before),
            json.dumps(after),
            timestamp(),
        ),
    )


def migrate_identities(db):
    """Preserve non-Latin merchant identities; retire ambiguous legacy rules without deleting them."""
    rows = list(db.execute("SELECT * FROM transactions"))
    changes = [
        (row, merchant_key(row["description"]))
        for row in rows
        if row["merchant_key"] != merchant_key(row["description"])
    ]
    changed_keys = {row["merchant_key"] for row, _ in changes}
    for rule in db.execute("SELECT * FROM rules WHERE identity_version=1").fetchall():
        if rule["merchant_key"] not in changed_keys:
            db.execute("UPDATE rules SET identity_version=2 WHERE id=?", (rule["id"],))
    # If normalization is changed again, already-versioned rules can also become ambiguous.
    for key in changed_keys:
        db.execute("UPDATE rules SET identity_version=0 WHERE merchant_key=?", (key,))
    for row in rows:
        key = merchant_key(row["description"])
        changed = key != row["merchant_key"]
        rule_affected = row["source"] == "rule" and row["merchant_key"] in changed_keys
        if not changed and not rule_affected:
            continue
        before = transaction_dict(row)
        needs_review = before["needs_review"]
        confidence = before["confidence"]
        reasons = before["reasons"]
        if before["source"] in {"rule", "engine"} and not needs_review:
            needs_review, confidence = True, 0
            reasons = ["Merchant identity has changed under stricter normalization. Confirm this category."]
        db.execute(
            """UPDATE transactions SET merchant_key=?,needs_review=?,confidence=?,reasons=?,
                      version=version+1 WHERE id=?""",
            (
                key,
                int(needs_review),
                confidence,
                json.dumps(reasons),
                before["id"],
            ),
        )
        after = transaction_dict(
            db.execute("SELECT * FROM transactions WHERE id=?", (before["id"],)).fetchone()
        )
        audit(db, before, after, "identity_revalidation")


def reconcile_refunds(db, new_candidates=()):
    """Rebuild exact reservations inside the caller's write transaction.

    Known/manual refunds take precedence. Existing contextual matches retain import-order
    priority over new backdated candidates. Their purchases must still be eligible and earlier.
    New candidates must be explicitly supplied, so unrelated pending rows aren't auto-confirmed.
    """
    rows = [dict(row) for row in db.execute("SELECT rowid AS sequence,* FROM transactions ORDER BY rowid")]
    new_ids = set(new_candidates)
    purchases = defaultdict(list)
    remaining = {}
    for row in rows:
        if (
            row["merchant_key"]
            and row["included"]
            and not row["needs_review"]
            and row["flow"] == "expense"
            and row["amount_minor"] < 0
            and row["category"] in EXPENSE_CATEGORIES
        ):
            purchases[(row["merchant_key"], row["currency"])].append(row)
            remaining[row["id"]] = -row["amount_minor"]
    for group in purchases.values():
        group.sort(key=lambda row: (row["date"], row["sequence"]))
    db.execute("DELETE FROM refund_allocations")

    def earlier(row):
        if not row["merchant_key"]:
            return []
        return [
            purchase
            for purchase in purchases.get((row["merchant_key"], row["currency"]), ())
            if purchase["date"] <= row["date"] and remaining[purchase["id"]] > 0
        ]

    def reserve(row, originals, partial=False):
        eligible = [purchase for purchase in originals if purchase["category"] == row["category"]]
        if not partial and sum(remaining[p["id"]] for p in eligible) < row["amount_minor"]:
            return False
        needed = row["amount_minor"]
        for purchase in eligible:
            allocated = min(needed, remaining[purchase["id"]])
            if allocated <= 0:
                continue
            db.execute(
                "INSERT INTO refund_allocations VALUES (?,?,?)", (row["id"], purchase["id"], allocated)
            )
            remaining[purchase["id"]] -= allocated
            needed -= allocated
            if needed == 0:
                break
        return needed == 0

    refunds = [row for row in rows if row["included"] and row["flow"] == "refund" and row["amount_minor"] > 0]
    for row in sorted(refunds, key=lambda row: (row["date"], row["sequence"])):
        if row["source"] != "context" and not row["needs_review"]:
            # A manual/known merchant refund can refer to an unimported purchase. Reserve
            # the available portion without rejecting an explicit bookkeeping decision.
            reserve(row, earlier(row), partial=True)

    existing = [row for row in refunds if row["source"] == "context" and not row["needs_review"]]
    fresh = [row for row in refunds if row["id"] in new_ids]
    for row in [
        *sorted(existing, key=lambda row: row["sequence"]),
        *sorted(fresh, key=lambda row: (row["date"], row["sequence"])),
    ]:
        originals = earlier(row)
        candidates = [
            {"id": p["id"], "category": p["category"], "amount_minor": -remaining[p["id"]]} for p in originals
        ]
        base = Decision(
            "uncategorized",
            "refund",
            0,
            True,
            json.loads(row["reasons"]),
            evidence=json.loads(row["evidence"]),
        )
        decision = resolve_refund(base, row["amount_minor"], candidates, 0)
        accepted = bool(row["merchant_key"]) and not decision.needs_review
        if row["id"] not in new_ids and decision.category != row["category"]:
            accepted = False
        if accepted:
            accepted = reserve({**row, "category": decision.category}, originals)
        if not accepted:
            if row["id"] in new_ids:
                continue
            decision = Decision(
                row["category"],
                "refund",
                0,
                True,
                [
                    "The earlier purchase identity, category, inclusion, or available refund "
                    "capacity changed. Confirm this refund."
                ],
                source="context",
            )
        else:
            decision = replace(decision, source="context")
        fields = {
            "category": decision.category,
            "flow": decision.flow,
            "confidence": decision.confidence,
            "needs_review": int(decision.needs_review),
            "reasons": json.dumps(decision.reasons),
            "evidence": json.dumps(decision.evidence),
            "source": decision.source,
            "engine_version": ENGINE_VERSION,
        }
        if all(row[key] == value for key, value in fields.items()):
            continue
        new = row["id"] in new_ids
        before = transaction_dict({key: value for key, value in row.items() if key != "sequence"})
        db.execute(
            """UPDATE transactions SET category=?,flow=?,confidence=?,needs_review=?,reasons=?,evidence=?,
                      source=?,engine_version=?,version=version+? WHERE id=?""",
            (*fields.values(), 0 if new else 1, row["id"]),
        )
        if not new:
            after = transaction_dict(
                db.execute("SELECT * FROM transactions WHERE id=?", (row["id"],)).fetchone()
            )
            audit(db, before, after, "refund_revalidation")
