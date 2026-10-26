"""Strict CSV and text-based PDF ingestion, with explicit financial conventions."""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, get_args

import pdfplumber

MAX_ROWS = 10000
MAX_PAGES = 40
Currency = Literal["USD", "GBP", "EUR", "CAD", "AUD", "PKR"]
CURRENCIES = set(get_args(Currency))
ALIASES = {
    "date": {"date", "transaction date", "posting date", "posted date", "post date", "trans date"},
    "description": {
        "description",
        "merchant",
        "payee",
        "details",
        "transaction description",
        "memo",
        "activity",
        "merchant name or transaction description",
    },
    "amount": {"amount", "transaction amount", "signed amount"},
    "debit": {"debit", "debits", "withdrawal", "withdrawals", "money out", "charge", "charges"},
    "credit": {"credit", "credits", "deposit", "deposits", "money in", "payment", "payments"},
    "currency": {"currency", "currency code"},
    "balance": {"balance", "running balance", "running bal", "running bal."},
    "type": {"type", "transaction type"},
}
HEADER_PRIORITY = {
    "date": ("transaction date", "trans date", "date", "posting date", "posted date", "post date"),
    "description": (
        "description",
        "transaction description",
        "merchant name or transaction description",
        "merchant",
        "payee",
        "activity",
        "details",
        "memo",
    ),
}
OPENING_LABELS = {"opening balance", "beginning balance", "balance brought forward"}
CLOSING_LABELS = {"closing balance", "ending balance", "balance carried forward"}


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedRow:
    date: str
    description: str
    amount_minor: int
    currency: str
    line: int
    fingerprint: str


@dataclass
class ParsedStatement:
    rows: list[ParsedRow]
    warnings: list[str]


def money(value: str, *, decimal_separator: str = ".", currency: str | None = None) -> int:
    raw = value.strip().replace("\u00a0", " ")
    if not raw:
        raise ParseError("Missing amount.")
    if decimal_separator not in {".", ","}:
        raise ParseError("Unsupported decimal separator.")
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1].strip()
    thousands = "," if decimal_separator == "." else "."
    escaped_sep, escaped_group = re.escape(decimal_separator), re.escape(thousands)
    number_pattern = rf"(?:[0-9]+|[0-9]{{1,3}}(?:{escaped_group}[0-9]{{3}})+)(?:{escaped_sep}[0-9]{{1,2}})?"
    match = re.fullmatch(
        rf"(?P<first>[+\-−])?\s*(?P<marker>USD|GBP|EUR|CAD|AUD|PKR|[$£€])?\s*"
        rf"(?P<second>[+\-−])?\s*(?P<number>{number_pattern})\s*(?P<direction>CR|DR)?",
        raw,
        re.I,
    )
    if not match or (match["first"] and match["second"]):
        raise ParseError(f"Invalid amount '{value[:60]}'. Use at most two decimal places.")
    sign = match["first"] or match["second"]
    if negative and sign:
        raise ParseError("Use a single amount sign or accounting parentheses.")
    negative = negative or sign in {"-", "−"}
    direction = (match["direction"] or "").upper()
    if direction == "CR" and negative or direction == "DR" and sign == "+":
        raise ParseError("Credit/debit marker conflicts with the amount sign.")
    marker = (match["marker"] or "").upper()
    if currency and marker:
        allowed = {"$": {"USD", "CAD", "AUD"}, "£": {"GBP"}, "€": {"EUR"}}.get(marker, {marker})
        if currency not in allowed:
            raise ParseError("Amount currency conflicts with the Currency column or import setting.")
    try:
        number = Decimal(match["number"].replace(thousands, "").replace(decimal_separator, "."))
    except InvalidOperation as exc:
        raise ParseError("Invalid amount.") from exc
    if negative:
        number = -abs(number)
    if direction:
        number = abs(number) * (-1 if direction == "DR" else 1)
    if abs(number) > Decimal("999999999999.99"):
        raise ParseError("Amount exceeds the supported limit.")
    return int(number * 100)


def parse_date(value: str, date_order: str) -> str:
    raw = value.strip()
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"]
    formats += ["%m/%d/%Y", "%m-%d-%Y"] if date_order == "mdy" else ["%d/%m/%Y", "%d-%m-%Y"]
    for fmt in formats:
        try:
            result = datetime.strptime(raw, fmt)
            if result.year < 1900 or result.year > 2100:
                break
            return result.date().isoformat()
        except ValueError:
            continue
    raise ParseError(f"Invalid date '{raw[:40]}'. Use full years and the selected date order.")


def header_map(row: list[str]) -> dict[str, int]:
    result = {}
    names = {}
    for index, value in enumerate(row):
        name = re.sub(r"[_\s]+", " ", str(value or "").strip().lower().lstrip("\ufeff*$ "))
        for key, variants in ALIASES.items():
            if name in variants:
                if key in result:
                    previous = names[key]
                    ranking = HEADER_PRIORITY.get(key)
                    if not ranking or previous == name:
                        raise ParseError(f"Multiple {key} columns; keep one unambiguous column.")
                    if ranking.index(name) >= ranking.index(previous):
                        continue
                result[key] = index
                names[key] = name
    return result


def is_header(mapping: dict) -> bool:
    return (
        "date" in mapping
        and "description" in mapping
        and bool({"amount", "debit", "credit"} & mapping.keys())
    )


def parse_table(
    table: list[list[str]],
    *,
    currency: str,
    date_order: str,
    convention: str,
    decimal_separator: str = ".",
    start_line: int = 1,
) -> list[ParsedRow]:
    header_index, mapping = -1, {}
    for index, row in enumerate(table[:25]):
        candidate = header_map(row)
        if is_header(candidate):
            header_index, mapping = index, candidate
            break
    if header_index < 0:
        raise ParseError("Could not find Date, Description and Amount (or Debit / Credit) columns.")
    if "amount" in mapping and ({"debit", "credit"} & mapping.keys()):
        raise ParseError("Both signed Amount and Debit / Credit columns found. Keep one amount format.")
    result = []
    errors = []
    opening_balance = None
    running_balance = None
    closing_balance = None
    declared_totals = None
    table_currency = None
    width = len(table[header_index])
    for index, values in enumerate(table[header_index + 1 :], header_index + 1):
        line = index + start_line
        if not any(str(v or "").strip() for v in values):
            continue
        if is_header(header_map(values)):
            if header_map(values) != mapping:
                raise ParseError(f"Row {line}: repeated header changes column order.")
            continue
        try:
            if len(values) != width:
                raise ParseError("Column count differs from the header.")

            def cell(name: str, values=values) -> str:
                return str(values[mapping[name]] or "").strip() if name in mapping else ""

            description = cell("description")
            if not description or len(description) > 500:
                raise ParseError("Description must contain 1–500 characters.")
            amount_cells = (cell("amount"), cell("debit"), cell("credit"))
            row_currency = cell("currency").upper() or table_currency or currency
            if row_currency not in CURRENCIES:
                raise ParseError(f"Unsupported currency '{row_currency}'.")
            if table_currency and row_currency != table_currency:
                raise ParseError("Mixed currencies cannot be reconciled in one statement.")
            table_currency = row_currency

            def parse_money(value, row_currency=row_currency):
                return money(value, decimal_separator=decimal_separator, currency=row_currency)

            label = description.casefold()
            if "balance" in mapping and label in OPENING_LABELS | CLOSING_LABELS:
                if any(value and parse_money(value) != 0 for value in amount_cells):
                    raise ParseError("Balance metadata must not contain a transaction amount.")
                parse_date(cell("date"), date_order)
                balance = parse_money(cell("balance"))
                if label in OPENING_LABELS:
                    if opening_balance is not None or result:
                        raise ParseError("Opening balance must appear once, before transactions.")
                    opening_balance = running_balance = balance
                else:
                    if closing_balance is not None:
                        raise ParseError("Multiple closing balance rows.")
                    closing_balance = balance
                continue
            if label in {"total", "totals"} and not cell("date") and {"debit", "credit"} <= mapping.keys():
                if declared_totals is not None or cell("balance"):
                    raise ParseError("Ambiguous totals row.")
                declared_totals = (
                    parse_money(cell("debit")),
                    parse_money(cell("credit")),
                )
                continue
            if closing_balance is not None or declared_totals is not None:
                raise ParseError("Transaction appears after a closing balance or totals row.")
            date = parse_date(cell("date"), date_order)
            if "amount" in mapping:
                amount = parse_money(cell("amount"))
                if convention == "card" and not re.search(r"(?:CR|DR)\s*\)?$", cell("amount"), re.I):
                    amount = -amount
            else:
                debit = parse_money(cell("debit")) if cell("debit") else 0
                credit = parse_money(cell("credit")) if cell("credit") else 0
                if debit < 0 or credit < 0:
                    raise ParseError("Debit / Credit columns must use positive values.")
                if debit and credit:
                    raise ParseError("Both Debit and Credit are nonzero; split the row.")
                if not cell("debit") and not cell("credit"):
                    raise ParseError("Missing Debit and Credit values.")
                amount = credit - debit
            transaction_type = cell("type").casefold()
            if (
                transaction_type in {"sale", "purchase", "debit"}
                and amount > 0
                or (transaction_type in {"return", "refund", "credit", "deposit"} and amount < 0)
            ):
                raise ParseError(
                    "Amount sign conflicts with the transaction Type. Check the selected sign convention."
                )
            if running_balance is not None:
                expected = running_balance + (
                    -amount if convention == "card" and "amount" in mapping else amount
                )
                reported = parse_money(cell("balance"))
                if expected != reported:
                    raise ParseError("Running balance does not reconcile with the transaction amount.")
                running_balance = reported
            fingerprint = hashlib.sha256(
                f"{date}|{description.upper()}|{amount}|{row_currency}".encode()
            ).hexdigest()
            result.append(ParsedRow(date, description, amount, row_currency, line, fingerprint))
        except ParseError as exc:
            errors.append(f"Row {line}: {exc}")
    if errors:
        raise ParseError(
            "No rows imported. "
            + " ".join(errors[:8])
            + (f" ({len(errors)} invalid rows in total.)" if len(errors) > 8 else "")
        )
    if closing_balance is not None and running_balance != closing_balance:
        raise ParseError("Closing balance does not reconcile with the imported transactions.")
    if declared_totals is not None:
        actual_totals = (
            -sum(r.amount_minor for r in result if r.amount_minor < 0),
            sum(r.amount_minor for r in result if r.amount_minor > 0),
        )
        if declared_totals != actual_totals:
            raise ParseError("Declared debit/credit totals do not reconcile with the imported transactions.")
    return result


def parse_csv(data: bytes, **options) -> ParsedStatement:
    try:
        content = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = data.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise ParseError("Use a UTF-8, BOM-marked UTF-16, or Windows-1252 CSV export.") from exc
    if "\x00" in content:
        raise ParseError("This does not appear to be a text CSV file.")
    lines = content.splitlines()
    # Detect delimiter from the actual transaction header, rather than bank preamble text.
    delimiter = None
    for line in lines[:25]:
        for candidate in (",", ";", "\t"):
            try:
                parsed_line = next(csv.reader([line], delimiter=candidate))
            except csv.Error as exc:
                raise ParseError(
                    "CSV field is too long or malformed. Re-export the statement as CSV."
                ) from exc
            if is_header(header_map(parsed_line)):
                delimiter = candidate
                break
        if delimiter:
            break
    if delimiter is None:
        raise ParseError("No transaction header found. Expected Date, Description, Amount or Debit / Credit.")
    try:
        table = list(csv.reader(io.StringIO(content), delimiter=delimiter, strict=True))
    except csv.Error as exc:
        raise ParseError("Malformed CSV quoting. Re-export the statement as CSV.") from exc
    rows = parse_table(table, **options)
    return validate(rows, [])


def parse_pdf(data: bytes, *, statement_year: int | None = None, **options) -> ParsedStatement:
    rows, warnings = [], []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise ParseError(f"PDF exceeds {MAX_PAGES} pages; split the statement.")
            from app.pdf_tables import parse_text_tables

            adapted = parse_text_tables(pdf, statement_year=statement_year, **options)
            if adapted is not None:
                return validate(adapted.rows, adapted.warnings)
            for page_number, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                recognized = False
                for table in tables:
                    if any(is_header(header_map(row)) for row in table[:25]):
                        recognized = True
                        rows.extend(parse_table(table, **options, start_line=1))
                if not recognized:
                    text = page.extract_text() or ""
                    # Conservative fallback: full ISO date, description, signed amount at line end.
                    candidates = []
                    for line in text.splitlines():
                        if re.match(r"^\d{4}-\d{2}-\d{2}\s", line):
                            match = re.fullmatch(
                                r"(\d{4}-\d{2}-\d{2})\s+(.+?)\s+([+-]?[$£€]?[\d,]+\.\d{2})", line
                            )
                            if not match:
                                raise ParseError(
                                    f"Page {page_number}: unreadable transaction line. Use a CSV export."
                                )
                            candidates.append(list(match.groups()))
                    if candidates:
                        rows.extend(parse_table([["Date", "Description", "Amount"], *candidates], **options))
                    elif not text.strip():
                        raise ParseError(
                            f"Page {page_number} is scanned or empty. "
                            "Export a text PDF or CSV; OCR is not supported."
                        )
                    else:
                        warnings.append(
                            f"Page {page_number} had no supported transaction table. "
                            "Compare the import with the original."
                        )
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(
            "Could not read this PDF. It may be encrypted, damaged, or unsupported. Try CSV."
        ) from exc
    return validate(rows, warnings)


def validate(rows: list[ParsedRow], warnings: list[str]) -> ParsedStatement:
    if not rows:
        raise ParseError(
            "No transactions found. Use a CSV export or a PDF with a supported transaction table."
        )
    if len(rows) > MAX_ROWS:
        raise ParseError(f"Maximum {MAX_ROWS:,} transactions per statement; split this file.")
    if len({r.currency for r in rows}) != 1:
        raise ParseError("Mixed currencies cannot be added together. Upload one currency per statement.")
    return ParsedStatement(rows, warnings)
