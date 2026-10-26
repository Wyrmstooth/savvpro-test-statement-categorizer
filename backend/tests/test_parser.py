import io

import pytest
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from app.parser import ParseError, money, parse_csv, parse_pdf

OPTIONS = {"currency": "USD", "date_order": "mdy", "convention": "bank"}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1,234.56", 123456),
        ("(59.99)", -5999),
        ("12.50 CR", 1250),
        ("12.50 DR", -1250),
        ("-0.01", -1),
        ("0", 0),
        ("GBP 12.00", 1200),
    ],
)
def test_exact_money(raw, expected):
    assert money(raw) == expected


@pytest.mark.parametrize("raw", ["NaN", "Inf", "12,34.56", "1.005", "", "1e3", "--1", "99999999999999"])
def test_reject_ambiguous_money(raw):
    with pytest.raises(ParseError):
        money(raw)


def test_european_decimal_is_explicit():
    assert money("1.234,56", decimal_separator=",") == 123456


def test_preamble_bom_semicolon_and_debit_credit():
    data = "\ufeffFictional bank statement\nDate;Payee;Debit;Credit\n03/04/2026;ADOBE;59.99;\n"
    result = parse_csv(data.encode(), **OPTIONS)
    assert result.rows[0].date == "2026-03-04"
    assert result.rows[0].amount_minor == -5999


def test_dmy_and_card_sign_are_explicit():
    result = parse_csv(
        b"Date,Description,Amount\n04/03/2026,FIGMA,15.00",
        **{
            **OPTIONS,
            "date_order": "dmy",
            "convention": "card",
        },
    )
    assert result.rows[0].date == "2026-03-04"
    assert result.rows[0].amount_minor == -1500


def test_explicit_credit_debit_markers_override_numeric_card_convention():
    data = b"Date,Description,Amount\n2026-10-01,ADOBE REFUND,10 CR\n2026-10-01,FIGMA,15 DR"
    rows = parse_csv(data, **{**OPTIONS, "convention": "card"}).rows
    assert [r.amount_minor for r in rows] == [1000, -1500]


def test_invalid_row_aborts_whole_import():
    data = b"Date,Description,Amount\n2026-10-01,ADOBE,-10\n2026-10-33,FIGMA,-15"
    with pytest.raises(ParseError, match="No rows imported.*Row 3"):
        parse_csv(data, **OPTIONS)


@pytest.mark.parametrize(
    "body",
    [
        "2026-10-01,ADOBE,10,20",  # Both directions cannot be nonzero.
        "2026-10-01,ADOBE,-10,",  # Debit cannot be negative.
        "2026-10-01,ADOBE,,",  # Missing is different from zero.
    ],
)
def test_bad_debit_credit(body):
    with pytest.raises(ParseError):
        parse_csv(("Date,Description,Debit,Credit\n" + body).encode(), **OPTIONS)


def test_mixed_currency_rejected():
    with pytest.raises(ParseError, match="Mixed currencies"):
        parse_csv(b"Date,Description,Amount,Currency\n2026-01-01,A,-1,USD\n2026-01-01,B,-1,GBP", **OPTIONS)


@pytest.mark.parametrize("amount", ["GBP 10", "£10", "EUR10", "€10"])
def test_embedded_currency_cannot_silently_become_usd(amount):
    with pytest.raises(ParseError, match="conflicts"):
        parse_csv(f"Date,Description,Amount\n2026-01-01,FIGMA,{amount}".encode(), **OPTIONS)


def test_no_silent_footer_or_column_loss():
    with pytest.raises(ParseError, match="Column count"):
        parse_csv(b"Date,Description,Amount\n2026-01-01,A,-1\nTotal,-1", **OPTIONS)


def make_pdf(rows):
    stream = io.BytesIO()
    table = Table(rows, colWidths=[100, 220, 90])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(stream).build([table])
    return stream.getvalue()


def test_real_pdf_table_extraction():
    data = make_pdf([["Date", "Description", "Amount"], ["2026-10-01", "ADOBE", "-59.99"]])
    result = parse_pdf(data, **OPTIONS)
    assert len(result.rows) == 1
    assert result.rows[0].amount_minor == -5999


def test_invalid_pdf_is_actionable():
    with pytest.raises(ParseError, match="Could not read"):
        parse_pdf(b"not a pdf", **OPTIONS)
