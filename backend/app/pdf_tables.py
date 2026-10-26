"""Bounded adapters for borderless text tables, using column geometry and reconciliation.

Only the explicit header profiles below are recognized. Missing years require a full
statement period or the user's supplied statement year; the current year is never guessed.
"""

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.parser import ParsedStatement, ParseError, money, parse_date, parse_table

PROFILES = {
    "date description withdrawals deposits balance": (
        "bank",
        ("Date", "Description", "Debit", "Credit", "Balance"),
    ),
    "date description debit credit balance": ("bank", ("Date", "Description", "Debit", "Credit", "Balance")),
    "activity date amount balance": ("activity", ("Description", "Date", "Amount", "Balance")),
    "date description amount balance": ("signed", ("Date", "Description", "Amount", "Balance")),
    "date merchant name or transaction description $ amount": ("card", ("Date", "Description", "Amount")),
}
NUMERIC_WORD = re.compile(r"^[+-]?[$£€]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}$")
DATE_WORD = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{4})?)$")
SECTIONS = {"payments and other credits", "purchase", "purchases", "interest charged", "fees charged"}


def word_lines(page):
    lines = []
    for word in sorted(page.extract_words(), key=lambda item: (item["top"], item["x0"])):
        if not lines or abs(lines[-1][0]["top"] - word["top"]) > 2.5:
            lines.append([word])
        else:
            lines[-1].append(word)
    return [sorted(line, key=lambda item: item["x0"]) for line in lines]


def statement_period(text: str, date_order: str, statement_year: int | None):
    # Scope inference to a literal statement-period line, not arbitrary dates in account history.
    numeric = re.compile(
        r"(?P<start>\d{1,2}/\d{1,2}/\d{2,4})\s*(?:through|to|[-–])\s*(?P<end>\d{1,2}/\d{1,2}/\d{2,4})", re.I
    )
    named = re.compile(r"([A-Za-z]+ \d{1,2}, \d{4})\s*(?:through|to|[-–])\s*([A-Za-z]+ \d{1,2}, \d{4})", re.I)
    periods = set()
    for line in text.splitlines():
        match = numeric.search(line) or named.search(line)
        if not match:
            continue
        start, end = match.groups()
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2}", end):
            if statement_year is None:
                continue
            end_short = int(end.rsplit("/", 1)[1])
            start_short = int(start.rsplit("/", 1)[1])
            if end_short != statement_year % 100 or start_short not in {end_short, (end_short - 1) % 100}:
                raise ParseError("The supplied statement year conflicts with the printed statement period.")
            start_year = statement_year if start_short == end_short else statement_year - 1
            start = start.rsplit("/", 1)[0] + f"/{start_year}"
            end = end.rsplit("/", 1)[0] + f"/{statement_year}"
        first, last = parse_date(start, date_order), parse_date(end, date_order)
        if first > last or (date.fromisoformat(last) - date.fromisoformat(first)).days > 370:
            raise ParseError("Unsupported or contradictory statement period.")
        periods.add((first, last))
    if len(periods) > 1:
        raise ParseError("Multiple statement periods found. Upload one complete statement at a time.")
    return next(iter(periods), None)


def complete_date(value: str, date_order: str, period, statement_year):
    if re.fullmatch(r"\d{1,2}/\d{1,2}", value):
        if period:
            candidates = []
            for year in range(int(period[0][:4]), int(period[1][:4]) + 1):
                try:
                    candidate = parse_date(f"{value}/{year}", date_order)
                    if period[0] <= candidate <= period[1]:
                        candidates.append(candidate)
                except ParseError:
                    continue
            if len(candidates) != 1:
                raise ParseError(f"Date {value} cannot be placed uniquely in the printed statement period.")
            return candidates[0]
        if statement_year is None:
            raise ParseError(
                "PDF transaction dates omit the year. Set Statement year under Format details, or use CSV."
            )
        return parse_date(f"{value}/{statement_year}", date_order)
    result = parse_date(value, date_order)
    if period and not period[0] <= result <= period[1]:
        raise ParseError(f"Transaction date {result} is outside the statement period.")
    return result


def parse_text_tables(pdf, *, statement_year=None, **options):
    pages = [word_lines(page) for page in pdf.pages]
    if not any(" ".join(w["text"].lower() for w in line) in PROFILES for lines in pages for line in lines):
        return None
    text = "\n".join(" ".join(w["text"] for w in line) for lines in pages for line in lines)
    period = statement_period(text, options["date_order"], statement_year)
    profile = None
    table = []
    source_lines = []
    references = {}
    active = False
    opening = closing = None
    declared_totals = None
    warnings = []
    global_line = 0
    for page_number, lines in enumerate(pages, 1):
        if not lines:
            raise ParseError(f"Page {page_number} is scanned or empty. Use a complete text PDF or CSV.")
        page_header = False
        for words in lines:
            global_line += 1
            raw = " ".join(word["text"] for word in words)
            label = raw.casefold()
            selected = PROFILES.get(label)
            if selected:
                kind, headers = selected
                if profile and kind != profile:
                    raise ParseError(
                        "Different transaction table layouts found in the same PDF. Split the statements."
                    )
                if kind == "card" and options["convention"] != "card":
                    raise ParseError(
                        "This PDF uses positive card charges. "
                        "Choose 'Charges are positive' for the amount convention."
                    )
                profile = kind
                if not table:
                    table.append(list(headers))
                page_header = active = True
                date_reference = next(word["x0"] for word in words if word["text"].casefold() == "date")
                # Financial columns are right-aligned against their printed headings.
                if kind == "bank":
                    references = {
                        "Debit": words[-3]["x1"],
                        "Credit": words[-2]["x1"],
                        "Balance": words[-1]["x1"],
                    }
                elif kind in {"activity", "signed"}:
                    references = {"Amount": words[-2]["x1"], "Balance": words[-1]["x1"]}
                else:
                    references = {"Amount": words[-1]["x1"]}
                continue
            # Authoritative metadata is never emitted as an expense/income transaction.
            match = re.fullmatch(r"Beginning balance on (\d{2}/\d{2}/\d{4}) (\$[\d,]+\.\d{2})", raw, re.I)
            if match:
                if period and parse_date(match[1], options["date_order"]) != period[0]:
                    raise ParseError("Opening balance date conflicts with the statement period.")
                value = money(match[2], currency=options["currency"])
                if opening is not None and value != opening:
                    raise ParseError("Conflicting opening balances in PDF.")
                opening = value
                continue
            match = re.fullmatch(
                r"(?:Ending balance on \d{2}/\d{2}/\d{4}|New Balance) (\$[\d,]+\.\d{2})", raw, re.I
            )
            if match:
                ending_date = re.search(r"\d{2}/\d{2}/\d{4}", raw)
                if period and ending_date and parse_date(ending_date[0], options["date_order"]) != period[1]:
                    raise ParseError("Closing balance date conflicts with the statement period.")
                value = money(match[1], currency=options["currency"])
                if closing is not None and value != closing:
                    raise ParseError("Conflicting closing balances in PDF.")
                closing = value
                continue
            match = re.fullmatch(r"Previous Balance (\$[\d,]+\.\d{2})", raw, re.I)
            if match:
                opening = money(match[1], currency=options["currency"])
                continue
            match = re.fullmatch(
                r"Total withdrawals ([\d,]+\.\d{2}) Total deposits ([\d,]+\.\d{2})", raw, re.I
            )
            if match:
                declared_totals = (
                    money(match[1], currency=options["currency"]),
                    money(match[2], currency=options["currency"]),
                )
                active = False
                continue
            if not active or label in SECTIONS:
                continue
            if label.startswith(("total interest for this period", "fictional sample", "your email address")):
                active = False
                continue
            date_tokens = [
                w for w in words if DATE_WORD.fullmatch(w["text"]) and abs(w["x0"] - date_reference) <= 20
            ]
            is_balance_row = profile == "activity" and label.startswith(
                ("opening balance ", "closing balance ")
            )
            if not date_tokens:
                # A monetary line inside a table is never silently discarded as decoration.
                if any(NUMERIC_WORD.fullmatch(w["text"]) for w in words) or re.match(r"^\d+[/\-]", raw):
                    raise ParseError(
                        f"Page {page_number}: unreadable transaction line. Use CSV or check the PDF layout."
                    )
                raise ParseError(
                    f"Page {page_number}: unsupported wrapped text inside the transaction table. Use CSV."
                )
            if len(date_tokens) != 1:
                raise ParseError(f"Page {page_number}: ambiguous transaction date columns.")
            date_word = date_tokens[0]
            full_date = complete_date(date_word["text"], options["date_order"], period, statement_year)
            cells = {key: "" for key in table[0]}
            cells["Date"] = full_date
            description = []
            for word in words:
                if word is date_word:
                    continue
                if NUMERIC_WORD.fullmatch(word["text"]):
                    key = min(references, key=lambda name: abs(word["x1"] - references[name]))
                    if abs(word["x1"] - references[key]) > 6 or cells[key]:
                        raise ParseError(
                            f"Page {page_number}: amount is not aligned with a unique financial column."
                        )
                    cells[key] = word["text"]
                else:
                    description.append(word["text"])
            cells["Description"] = " ".join(description)
            if is_balance_row:
                value = money(cells["Balance"], currency=options["currency"])
                if label.startswith("opening"):
                    if opening is not None or len(table) > 1:
                        raise ParseError("Multiple opening balances or accounts found. Split the statements.")
                    opening = value
                else:
                    closing = value
                    active = False
                continue
            table.append([cells[header] for header in table[0]])
            source_lines.append(global_line)
        if not page_header:
            warnings.append(
                f"Page {page_number} had no supported transaction table. "
                "Compare the import with the original."
            )

    if len(table) <= 1:
        raise ParseError("A transaction header was found, but no supported transaction rows were readable.")
    # Add a verified opening balance to use the same running-balance checks as CSV.
    if "Balance" in table[0] and opening is not None:
        first_date = next(row[table[0].index("Date")] for row in table[1:])
        opening_row = {key: "" for key in table[0]}
        opening_row.update(
            Date=first_date, Description="Opening balance", Balance=str(Decimal(opening) / 100)
        )
        table.insert(1, [opening_row[key] for key in table[0]])
    rows = parse_table(table, **options)
    net = sum(row.amount_minor for row in rows)
    if opening is not None and closing is not None:
        expected = opening - net if profile == "card" else opening + net
        if expected != closing:
            raise ParseError(
                "PDF opening balance plus transaction movement does not reconcile with its closing balance."
            )
    else:
        warnings.append(
            "PDF has no complete opening/closing reconciliation. "
            "Check every transaction against the original."
        )
    if declared_totals is not None:
        actual = (
            -sum(r.amount_minor for r in rows if r.amount_minor < 0),
            sum(r.amount_minor for r in rows if r.amount_minor > 0),
        )
        if actual != declared_totals:
            raise ParseError(
                "PDF transaction totals do not reconcile with its declared withdrawals and deposits."
            )
    return ParsedStatement(
        [replace(row, line=line) for row, line in zip(rows, source_lines, strict=True)], warnings
    )
