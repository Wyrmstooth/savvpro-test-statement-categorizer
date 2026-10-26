import csv
import hashlib
import io
import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.engine import CATEGORIES, ENGINE_VERSION, EXPENSE_CATEGORIES, decide, merchant_key, resolve_refund
from app.parser import CURRENCIES, ParseError, ParsedStatement, parse_csv, parse_pdf
from app.storage import connect, initialize, transaction_dict

ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 10 * 1024 * 1024


def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(UTC).isoformat()


def decimal_amount(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    units, cents = divmod(abs(minor), 100)
    return f"{sign}{units}.{cents:02d}"


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str
    flow: Literal["expense", "refund", "income", "transfer", "neutral"]
    version: int = Field(ge=1)
    included: bool = True
    note: str = Field(default="", max_length=500)
    remember: bool = False


class BulkReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[Annotated[dict, Field()]] = Field(min_length=1, max_length=200)
    category: str


def summarize(rows: list[dict], currency: str) -> dict:
    active = [r for r in rows if r["included"]]
    accepted = [r for r in active if not r["needs_review"]]

    def totals(source):
        return {
            "spending_minor": -sum(r["amount_minor"] for r in source if r["category"] in EXPENSE_CATEGORIES),
            "income_minor": sum(r["amount_minor"] for r in source if r["category"] == "income"),
            "transfer_out_minor": -sum(r["amount_minor"] for r in source
                                      if r["category"] == "transfer" and r["amount_minor"] < 0),
            "transfer_in_minor": sum(r["amount_minor"] for r in source
                                     if r["category"] == "transfer" and r["amount_minor"] > 0),
        }

    groups = []
    for key, category in CATEGORIES.items():
        members = [r for r in active if r["category"] == key]
        groups.append({
            "id": key, **category, "count": len(members),
            "net_minor": sum(r["amount_minor"] for r in members),
            "review_count": sum(r["needs_review"] for r in members),
            "confirmed_net_minor": sum(r["amount_minor"] for r in members if not r["needs_review"]),
        })
    return {
        "currency": currency, "total": len(rows), "review_count": sum(r["needs_review"] for r in rows),
        "ready_count": sum(not r["needs_review"] for r in rows),
        "excluded_count": sum(not r["included"] for r in rows),
        "refund_minor": sum(r["amount_minor"] for r in active if r["flow"] == "refund"),
        "cash_in_minor": sum(r["amount_minor"] for r in active if r["amount_minor"] > 0),
        "cash_out_minor": -sum(r["amount_minor"] for r in active if r["amount_minor"] < 0),
        "net_movement_minor": sum(r["amount_minor"] for r in active),
        "unresolved_net_minor": sum(r["amount_minor"] for r in active if r["needs_review"]),
        "unclassified_credits_minor": sum(r["amount_minor"] for r in active
                                          if r["category"] == "uncategorized" and r["amount_minor"] > 0),
        "confirmed": totals(accepted), "provisional": totals(active), "categories": groups,
    }


def create_app(db_path: str | None = None) -> FastAPI:
    database = db_path or os.getenv("FOLIO_DB", str(ROOT / "data" / "folio.db"))

    @asynccontextmanager
    async def lifespan(_app):
        initialize(database)
        yield

    app = FastAPI(title="Folio", version=ENGINE_VERSION, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    app.state.database = database

    @app.middleware("http")
    async def local_request_guard(request, call_next):
        # This is a local single-user app. Reject cross-origin mutations, including localhost CSRF.
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            allowed = {str(request.base_url).rstrip("/"), "http://127.0.0.1:5173", "http://localhost:5173",
                       "http://127.0.0.1:4173", "http://localhost:4173"}
            if origin not in allowed:
                return Response("Cross-origin request rejected", status_code=403)
        if request.method == "POST" and request.headers.get("content-length", "0").isdigit():
            if int(request.headers.get("content-length", "0")) > MAX_BYTES + 1024 * 128:
                return Response("File exceeds 10 MB", status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "engine": ENGINE_VERSION}

    def insert_statement(data: bytes, filename: str, parsed: ParsedStatement):
        sha = hashlib.sha256(data).hexdigest()
        statement_id = uid()
        rows = parsed.rows
        with connect(database) as db:
            # Acquire writer lock before checking duplicate file/row identities.
            db.execute("BEGIN IMMEDIATE")
            duplicate_file = db.execute("SELECT id FROM statements WHERE sha=?", (sha,)).fetchone()
            if duplicate_file:
                raise HTTPException(409, {"message": "This statement is already imported.",
                                          "statement_id": duplicate_file["id"]})
            db.execute("INSERT INTO statements VALUES (?,?,?,?,?,?,?,?,?)", (
                statement_id, Path(filename.replace("\\", "/")).name[:200], sha, rows[0].currency,
                min(r.date for r in rows), max(r.date for r in rows), len(rows), json.dumps(parsed.warnings), now(),
            ))
            known = {r[0] for r in db.execute("SELECT fingerprint FROM transactions")}
            learned_rules = {(r["merchant_key"], r["direction"]): dict(r) for r in db.execute("SELECT * FROM rules")}
            duplicate_count = 0
            # Purchases precede refunds on a shared date, irrespective of CSV sort order.
            for row in sorted(rows, key=lambda r: (r.date, r.amount_minor > 0, r.line)):
                key = merchant_key(row.description)
                direction = "expense" if row.amount_minor < 0 else "income"
                decision = decide(row.description, row.amount_minor, learned_rules.get((key, direction)))
                if decision.category == "uncategorized" and decision.flow == "refund":
                    originals = [dict(r) for r in db.execute(
                        """SELECT id,category,amount_minor FROM transactions WHERE merchant_key=? AND currency=?
                           AND date<=? AND amount_minor<0 AND needs_review=0 AND included=1
                           AND duplicate=0 AND flow='expense'""", (key, row.currency, row.date),
                    )]
                    refunded = db.execute(
                        """SELECT COALESCE(SUM(amount_minor),0) FROM transactions WHERE merchant_key=?
                           AND currency=? AND date<=? AND flow='refund' AND needs_review=0 AND included=1""",
                        (key, row.currency, row.date),
                    ).fetchone()[0]
                    decision = resolve_refund(decision, row.amount_minor, originals, refunded)
                duplicate = row.fingerprint in known
                known.add(row.fingerprint)
                reasons = list(decision.reasons)
                if duplicate:
                    duplicate_count += 1
                    reasons.append("Possible duplicate: same date, original description, amount and currency. Keep or exclude explicitly.")
                if parsed.warnings:
                    reasons.append("PDF extraction needs reconciliation with the original statement.")
                db.execute("""INSERT INTO transactions
                    (id,statement_id,date,description,merchant_key,amount_minor,currency,line,fingerprint,
                     category,flow,confidence,needs_review,reasons,evidence,source,engine_version,duplicate)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    uid(), statement_id, row.date, row.description, key, row.amount_minor, row.currency,
                    row.line, row.fingerprint, decision.category, decision.flow, decision.confidence,
                    int(decision.needs_review or duplicate or bool(parsed.warnings)), json.dumps(reasons),
                    json.dumps(decision.evidence), decision.source, ENGINE_VERSION, int(duplicate),
                ))
        return {"statement_id": statement_id, "row_count": len(rows), "duplicate_count": duplicate_count,
                "warnings": parsed.warnings}

    @app.post("/api/statements", status_code=201)
    async def upload(
        file: Annotated[UploadFile, File()],
        currency: str = "USD",
        date_order: Literal["mdy", "dmy"] = "mdy",
        convention: Literal["bank", "card"] = "bank",
        decimal_separator: Literal[".", ","] = ".",
    ):
        if currency not in CURRENCIES:
            raise HTTPException(422, "Unsupported currency.")
        filename = file.filename or "statement"
        extension = Path(filename).suffix.lower()
        if extension not in {".csv", ".pdf"}:
            raise HTTPException(415, "Choose a CSV or text-based PDF statement.")
        data = await file.read(MAX_BYTES + 1)
        await file.close()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "File exceeds 10 MB. Split the statement.")
        if not data:
            raise HTTPException(422, "The uploaded file is empty.")
        try:
            parsed = await run_in_threadpool(parse_csv if extension == ".csv" else parse_pdf, data,
                                             currency=currency, date_order=date_order, convention=convention,
                                             decimal_separator=decimal_separator)
            return await run_in_threadpool(insert_statement, data, filename, parsed)
        except ParseError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/demo", status_code=201)
    def demo():
        data = (ROOT / "samples" / "creative-studio-october.csv").read_bytes()
        parsed = parse_csv(data, currency="USD", date_order="mdy", convention="bank")
        return insert_statement(data, "Creative studio · October 2026.csv", parsed)

    def scoped_rows(db, statement_id, currency):
        if statement_id:
            statement = db.execute("SELECT * FROM statements WHERE id=?", (statement_id,)).fetchone()
            if not statement:
                raise HTTPException(404, "Statement not found.")
            currency = statement["currency"]
            result = db.execute("SELECT * FROM transactions WHERE statement_id=? ORDER BY date DESC,rowid DESC",
                                (statement_id,))
        else:
            result = db.execute("SELECT * FROM transactions WHERE currency=? ORDER BY date DESC,rowid DESC", (currency,))
        return [transaction_dict(r) for r in result], currency

    @app.get("/api/workspace")
    def workspace(statement_id: str | None = None, currency: str = "USD"):
        with connect(database) as db:
            statements = [dict(r) for r in db.execute("SELECT * FROM statements ORDER BY created_at DESC")]
            for statement in statements:
                statement["warnings"] = json.loads(statement["warnings"])
            rows, selected_currency = scoped_rows(db, statement_id, currency)
            rules = [dict(r) for r in db.execute("SELECT * FROM rules ORDER BY created_at DESC")]
        return {"statements": statements, "transactions": rows, "summary": summarize(rows, selected_currency),
                "rules": rules, "categories": [{"id": key, **value} for key, value in CATEGORIES.items()],
                "currencies": sorted({r["currency"] for r in statements}), "engine_version": ENGINE_VERSION}

    def apply_review(db, transaction_id, body: Review):
        raw = db.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()
        if not raw:
            raise HTTPException(404, "Transaction not found.")
        before = transaction_dict(raw)
        if body.version != before["version"]:
            raise HTTPException(409, "This transaction changed. Refresh and try again.")
        if body.category not in CATEGORIES or body.category == "uncategorized":
            raise HTTPException(422, "Choose a category before confirming.")
        amount = before["amount_minor"]
        if body.flow == "expense" and amount >= 0 or body.flow in {"refund", "income"} and amount <= 0:
            raise HTTPException(422, "Money direction conflicts with the signed amount.")
        if body.flow == "neutral" and amount != 0:
            raise HTTPException(422, "Only zero-value rows can be neutral.")
        if (body.category == "transfer") != (body.flow == "transfer"):
            raise HTTPException(422, "Transfer category and flow must agree.")
        if (body.category == "income") != (body.flow == "income"):
            raise HTTPException(422, "Income category and flow must agree.")
        reasons = ["Confirmed by you."]
        if not body.included:
            reasons.append("Excluded from all totals and category summaries.")
        db.execute("""UPDATE transactions SET category=?,flow=?,needs_review=0,confidence=100,source='user',
                      reasons=?,note=?,included=?,version=version+1 WHERE id=?""", (
            body.category, body.flow, json.dumps(reasons), body.note.strip(), int(body.included), transaction_id,
        ))
        if body.remember:
            if before["duplicate"] or amount == 0 or not before["merchant_key"]:
                raise HTTPException(422, "Duplicate and zero-value rows cannot create merchant rules.")
            direction = "expense" if amount < 0 else "income"
            db.execute("""INSERT INTO rules VALUES (?,?,?,?,?) ON CONFLICT(merchant_key,direction)
                          DO UPDATE SET category=excluded.category,created_at=excluded.created_at""",
                       (uid(), before["merchant_key"], direction, body.category, now()))
        after = transaction_dict(db.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone())
        db.execute("INSERT INTO audit VALUES (?,?,?,?,?,?)", (
            uid(), transaction_id, "review", json.dumps(before), json.dumps(after), now(),
        ))
        return after

    @app.patch("/api/transactions/{transaction_id}")
    def review(transaction_id: str, body: Review):
        with connect(database) as db:
            db.execute("BEGIN IMMEDIATE")
            return apply_review(db, transaction_id, body)

    @app.post("/api/review-batch")
    def review_batch(body: BulkReview):
        if body.category not in CATEGORIES or body.category == "uncategorized":
            raise HTTPException(422, "Choose a category before confirming.")
        with connect(database) as db:
            db.execute("BEGIN IMMEDIATE")
            updated = []
            ids = set()
            for item in body.items:
                transaction_id = item.get("id")
                if not isinstance(transaction_id, str) or not isinstance(item.get("version"), int):
                    raise HTTPException(422, "Each row needs an id and version.")
                if transaction_id in ids:
                    raise HTTPException(422, "Duplicate transaction id in batch.")
                ids.add(transaction_id)
                row = db.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()
                if not row:
                    raise HTTPException(404, "Transaction not found.")
                if row["duplicate"]:
                    raise HTTPException(422, "Review possible duplicates individually.")
                flow = "transfer" if body.category == "transfer" else (
                    "income" if body.category == "income" else (
                        "refund" if row["amount_minor"] > 0 else "expense"
                    )
                )
                updated.append(apply_review(db, transaction_id, Review(
                    category=body.category, flow=flow, version=item["version"],
                    included=bool(row["included"]), note=row["note"],
                )))
        return {"updated": len(updated)}

    @app.get("/api/transactions/{transaction_id}/history")
    def history(transaction_id: str):
        with connect(database) as db:
            if not db.execute("SELECT 1 FROM transactions WHERE id=?", (transaction_id,)).fetchone():
                raise HTTPException(404, "Transaction not found.")
            result = [dict(r) for r in db.execute(
                "SELECT * FROM audit WHERE transaction_id=? ORDER BY created_at DESC", (transaction_id,))]
        for row in result:
            row["before"] = json.loads(row.pop("before_json"))
            row["after"] = json.loads(row.pop("after_json"))
        return result

    @app.delete("/api/rules/{rule_id}", status_code=204)
    def delete_rule(rule_id: str):
        with connect(database) as db:
            if not db.execute("DELETE FROM rules WHERE id=?", (rule_id,)).rowcount:
                raise HTTPException(404, "Rule not found.")
        return Response(status_code=204)

    @app.get("/api/export")
    def export(statement_id: str | None = None, currency: str = "USD",
               kind: Literal["transactions", "summary"] = "transactions",
               confirmed_only: bool = False):
        with connect(database) as db:
            rows, selected_currency = scoped_rows(db, statement_id, currency)
        if confirmed_only:
            rows = [r for r in rows if not r["needs_review"]]
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        if kind == "summary":
            writer.writerow(["Category", "Currency", "Net amount", "Transactions", "Needs review", "Confirmed net amount"])
            for group in summarize(rows, selected_currency)["categories"]:
                writer.writerow([group["name"], selected_currency, decimal_amount(group["net_minor"]),
                                 group["count"], group["review_count"], decimal_amount(group["confirmed_net_minor"])])
        else:
            writer.writerow(["Date", "Description", "Amount", "Currency", "Category", "Flow", "Status",
                             "Included", "Confidence score", "Reason", "Note", "Engine version", "Source row"])
            for row in rows:
                values = [row["date"], row["description"], decimal_amount(row["amount_minor"]), row["currency"],
                          CATEGORIES[row["category"]]["name"], row["flow"],
                          "Needs review" if row["needs_review"] else "Confirmed" if row["source"] == "user" else "Categorized",
                          "Yes" if row["included"] else "No", row["confidence"], " ".join(row["reasons"]),
                          row["note"], row["engine_version"], row["line"]]
                # Only free text is escaped: numeric amounts remain usable in spreadsheets.
                for index in (1, 9, 10):
                    if str(values[index]).lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                        values[index] = "'" + str(values[index])
                writer.writerow(values)
        return Response(stream.getvalue().encode("utf-8-sig"), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="folio-{kind}-{selected_currency}.csv"'})

    @app.get("/api/sample")
    def sample():
        return Response((ROOT / "samples" / "creative-studio-october.csv").read_bytes(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="creative-studio-october.csv"'})

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
