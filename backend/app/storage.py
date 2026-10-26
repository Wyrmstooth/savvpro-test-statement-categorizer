import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS statements (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, sha TEXT NOT NULL UNIQUE,
    currency TEXT NOT NULL, date_start TEXT NOT NULL, date_end TEXT NOT NULL,
    row_count INTEGER NOT NULL, warnings TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY, statement_id TEXT NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
    date TEXT NOT NULL, description TEXT NOT NULL, merchant_key TEXT NOT NULL,
    amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, line INTEGER NOT NULL,
    fingerprint TEXT NOT NULL, category TEXT NOT NULL, flow TEXT NOT NULL,
    confidence INTEGER NOT NULL, needs_review INTEGER NOT NULL, reasons TEXT NOT NULL,
    evidence TEXT NOT NULL, source TEXT NOT NULL, engine_version TEXT NOT NULL,
    duplicate INTEGER NOT NULL DEFAULT 0, included INTEGER NOT NULL DEFAULT 1,
    note TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_transaction_statement ON transactions(statement_id);
CREATE INDEX IF NOT EXISTS ix_transaction_fingerprint ON transactions(fingerprint);
CREATE INDEX IF NOT EXISTS ix_transaction_merchant_date ON transactions(merchant_key,currency,date);
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY, merchant_key TEXT NOT NULL, direction TEXT NOT NULL,
    category TEXT NOT NULL, created_at TEXT NOT NULL,
    identity_version INTEGER NOT NULL DEFAULT 2, UNIQUE(merchant_key, direction)
);
CREATE TABLE IF NOT EXISTS refund_allocations (
    refund_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    purchase_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
    PRIMARY KEY(refund_id,purchase_id)
);
CREATE INDEX IF NOT EXISTS ix_refund_purchase ON refund_allocations(purchase_id);
CREATE TABLE IF NOT EXISTS audit (
    id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    action TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@contextmanager
def connect(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path: str):
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        if "identity_version" not in {row[1] for row in db.execute("PRAGMA table_info(rules)")}:
            db.execute("ALTER TABLE rules ADD COLUMN identity_version INTEGER NOT NULL DEFAULT 1")
        from app.refunds import migrate_identities, reconcile_refunds

        migrate_identities(db)
        reconcile_refunds(db)


def transaction_dict(row) -> dict:
    value = dict(row)
    for key in ("reasons", "evidence"):
        value[key] = json.loads(value[key])
    for key in ("needs_review", "duplicate", "included"):
        value[key] = bool(value[key])
    return value
