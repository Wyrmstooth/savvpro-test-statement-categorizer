"""Strict CSV and text-based PDF ingestion, with explicit financial conventions."""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

MAX_ROWS = 10000
MAX_PAGES = 40
CURRENCIES = {"USD", "GBP", "EUR", "CAD", "AUD", "PKR"}
ALIASES = {
    "date": {"date", "transaction date", "posting date", "posted date", "trans date"},
    "description": {"description", "merchant", "payee", "details", "transaction description", "memo"},
    "amount": {"amount", "transaction amount", "signed amount"},
    "debit": {"debit", "debits", "withdrawal", "withdrawals", "money out", "charge", "charges"},
    "credit": {"credit", "credits", "deposit", "deposits", "money in", "payment", "payments"},
    "currency": {"currency", "currency code"},
}


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


def money(value: str, *, decimal_separator: str = ".") -> int:
    raw = value.strip().replace("\u00a0", " ")
    if not raw:
        raise ParseError("Missing amount.")
    negative = raw.startswith("(") and raw.endswith(")")
    suffix = re.search(r"\s*(CR|DR)$", raw, re.I)
    if suffix:
        raw = raw[: suffix.start()].strip()
    raw = re.sub(r"^(?:USD|GBP|EUR|CAD|AUD|PKR)\s*", "", raw, flags=re.I)
    raw = re.sub(r"[$£€]", "", raw).strip()
    if negative:
        raw = raw[1:-1]
    # Validate grouping before removing it; malformed numbers are never silently changed.
    thousands = "," if decimal_separator == "." else "."
    escaped_sep, escaped_group = re.escape(decimal_separator), re.escape(thousands)
    pattern = rf"[+-]?(?:\d+|\d{{1,3}}(?:{escaped_group}\d{{3}})+)(?:{escaped_sep}\d{{1,2}})?"
    if not re.fullmatch(pattern, raw):
        raise ParseError(f"Invalid amount '{value[:60]}'. Use at most two decimal places.")
    try:
        number = Decimal(raw.replace(thousands, "").replace(decimal_separator, "."))
    except InvalidOperation as exc:
        raise ParseError("Invalid amount.") from exc
    if negative:
        number = -abs(number)
    if suffix:
        number = abs(number) * (-1 if suffix.group(1).upper() == "DR" else 1)
    if abs(number) > Decimal("999999999999.99"):
        raise ParseError("Amount exceeds the supported limit.")
    return int(number * 100)


def parse_date(value: str, date_order: str) -> str:
    raw = value.strip()
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y"]
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
    for index, value in enumerate(row):
        name = re.sub(r"[_\s]+", " ", str(value or "").strip().lower().lstrip("\ufeff"))
        for key, variants in ALIASES.items():
            if name in variants:
                if key in result:
                    raise ParseError(f"Multiple {key} columns; keep one unambiguous column.")
                result[key] = index
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

            def cell(name: str) -> str:
                return str(values[mapping[name]] or "").strip() if name in mapping else ""

            description = cell("description")
            if not description or len(description) > 500:
                raise ParseError("Description must contain 1–500 characters.")
            date = parse_date(cell("date"), date_order)
            row_currency = cell("currency").upper() or currency
            if row_currency not in CURRENCIES:
                raise ParseError(f"Unsupported currency '{row_currency}'.")
            for amount_text in (cell("amount"), cell("debit"), cell("credit")):
                marker = re.search(r"\b(USD|GBP|EUR|CAD|AUD|PKR)(?=\s*[-+($£€\d])", amount_text, re.I)
                if marker and marker.group(1).upper() != row_currency:
                    raise ParseError("Amount currency conflicts with the Currency column or import setting.")
                for symbol, allowed in (("£", {"GBP"}), ("€", {"EUR"}), ("$", {"USD", "CAD", "AUD"})):
                    if symbol in amount_text and row_currency not in allowed:
                        raise ParseError(f"The {symbol} symbol conflicts with currency {row_currency}.")
            if "amount" in mapping:
                amount = money(cell("amount"), decimal_separator=decimal_separator)
                if convention == "card" and not re.search(r"(?:CR|DR)\s*$", cell("amount"), re.I):
                    amount = -amount
            else:
                debit = money(cell("debit"), decimal_separator=decimal_separator) if cell("debit") else 0
                credit = money(cell("credit"), decimal_separator=decimal_separator) if cell("credit") else 0
                if debit < 0 or credit < 0:
                    raise ParseError("Debit / Credit columns must use positive values.")
                if debit and credit:
                    raise ParseError("Both Debit and Credit are nonzero; split the row.")
                if not cell("debit") and not cell("credit"):
                    raise ParseError("Missing Debit and Credit values.")
                amount = credit - debit
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
    return result


def parse_csv(data: bytes, **options) -> ParsedStatement:
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = data.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise ParseError("Use a UTF-8 or Windows-1252 CSV export.") from exc
    if "\x00" in content:
        raise ParseError("This does not appear to be a text CSV file.")
    lines = content.splitlines()
    # Detect delimiter from the actual transaction header, rather than bank preamble text.
    delimiter = None
    for line in lines[:25]:
        for candidate in (",", ";", "\t"):
            if is_header(header_map(next(csv.reader([line], delimiter=candidate)))):
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


def parse_pdf(data: bytes, **options) -> ParsedStatement:
    rows, warnings = [], []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise ParseError(f"PDF exceeds {MAX_PAGES} pages; split the statement.")
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
                            f"Page {page_number} is scanned or empty. Export a text PDF or CSV; OCR is not supported."
                        )
                    else:
                        warnings.append(
                            f"Page {page_number} had no supported transaction table. Compare the import with the original."
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
