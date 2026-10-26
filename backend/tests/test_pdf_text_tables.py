import io

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app.main import create_app
from app.parser import ParseError, parse_pdf

OPTIONS = {"currency": "USD", "date_order": "mdy", "convention": "bank"}


def bank_pdf(*, corrupt=False, cross_year=False, unexpected=False, offset=0, multi_page=False):
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)

    def header(y):
        pdf.setFont("Helvetica", 9)
        for x, text in [(40, "Date"), (92, "Description")]:
            pdf.drawString(x, y, text)
        for x, text in [(410, "Withdrawals"), (490, "Deposits"), (572, "Balance")]:
            pdf.drawRightString(x, y, text)

    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, 780, "FICTIONAL TEST DATA - not a bank record")
    period = (
        "December 1, 2025 through January 31, 2026"
        if cross_year
        else "October 1, 2026 through October 31, 2026"
    )
    pdf.drawString(40, 760, period)
    start = "12/01/2025" if cross_year else "10/01/2026"
    pdf.drawString(40, 740, f"Beginning balance on {start} $100.00")
    end = "01/31/2026" if cross_year else "10/31/2026"
    pdf.drawString(40, 720, f"Ending balance on {end} $135.00")
    header(690)
    pdf.drawString(40, 670, "12/30" if cross_year else "10/02")
    pdf.drawString(92, 670, "FIGMA invoice 10/01")
    pdf.drawRightString(410 + offset, 670, "15.00")
    pdf.drawRightString(572, 670, "86.00" if corrupt else "85.00")
    if multi_page:
        pdf.drawString(40, 650, "Fictional sample - page one")
        pdf.showPage()
        header(750)
        y = 730
    else:
        y = 650
    if unexpected:
        pdf.drawString(40, y, "MALFORMED TRANSACTION 30.00")
        y -= 20
    pdf.drawString(40, y, "01/03" if cross_year else "10/03")
    pdf.drawString(92, y, "CLIENT PAYMENT EXAMPLE STUDIO")
    pdf.drawRightString(490, y, "50.00")
    pdf.drawRightString(572, y, "135.00")
    pdf.drawString(40, y - 20, "Total withdrawals 15.00 Total deposits 50.00")
    pdf.save()
    return stream.getvalue()


def card_pdf(*, extra_period=False, malformed_date=False):
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.setFont("Helvetica", 9)
    for y, text in [
        (780, "FICTIONAL TEST DATA - not a bank record"),
        (760, "Opening/Closing Date 09/01/26 - 09/30/26"),
        (740, "Previous Balance $200.00"),
        (720, "New Balance $107.00"),
    ]:
        pdf.drawString(40, y, text)
    if extra_period:
        pdf.drawString(40, 700, "Opening/Closing Date 08/01/26 - 08/31/26")
    pdf.drawString(40, 670, "Date")
    pdf.drawString(100, 670, "Merchant Name or Transaction Description")
    pdf.drawRightString(572, 670, "$ Amount")
    rows = [
        ("09/01", "FIGMA", "15.00"),
        ("09/05", "PAYMENT THANK YOU", "-100.00"),
        ("09/14", "OFFICE DEPOT RETURN", "-10.00"),
        ("09/30", "PURCHASE INTEREST CHARGE", "2.00"),
    ]
    for index, (day, description, amount) in enumerate(rows):
        y = 650 - index * 20
        pdf.drawString(40, y, "09/XX" if malformed_date and index == 1 else day)
        pdf.drawString(100, y, description)
        pdf.drawRightString(572, y, amount)
    pdf.drawString(40, 550, "TOTAL INTEREST FOR THIS PERIOD $2.00")
    pdf.save()
    return stream.getvalue()


def test_borderless_bank_table_reconciles_and_preserves_description_dates():
    result = parse_pdf(bank_pdf(), **OPTIONS)
    assert len(result.rows) == 2
    assert result.rows[0].description == "FIGMA invoice 10/01"
    assert result.rows[0].date == "2026-10-02"
    assert [r.amount_minor for r in result.rows] == [-1500, 5000]
    assert result.warnings == []


def test_repeated_pdf_headers_do_not_duplicate_rows():
    result = parse_pdf(bank_pdf(multi_page=True), **OPTIONS)
    assert len(result.rows) == 2
    assert result.rows[0].line < result.rows[1].line
    assert sum(r.amount_minor for r in result.rows) == 3500


def test_year_rollover_uses_statement_period_instead_of_current_year():
    rows = parse_pdf(bank_pdf(cross_year=True), **OPTIONS).rows
    assert [row.date for row in rows] == ["2025-12-30", "2026-01-03"]


@pytest.mark.parametrize(
    "overrides,pattern",
    [
        ({"corrupt": True}, "Running balance"),
        ({"unexpected": True}, "unreadable transaction"),
        ({"offset": 20}, "not aligned"),
    ],
)
def test_pdf_does_not_hide_corrupt_or_unreadable_rows(overrides, pattern):
    with pytest.raises(ParseError, match=pattern):
        parse_pdf(bank_pdf(**overrides), **OPTIONS)


def test_short_card_dates_require_explicit_year_and_correct_convention():
    with pytest.raises(ParseError, match="positive card charges"):
        parse_pdf(card_pdf(), **OPTIONS)
    with pytest.raises(ParseError, match="Statement year"):
        parse_pdf(card_pdf(), **{**OPTIONS, "convention": "card"})
    result = parse_pdf(card_pdf(), statement_year=2026, **{**OPTIONS, "convention": "card"})
    assert len(result.rows) == 4
    assert [r.amount_minor for r in result.rows] == [-1500, 10000, 1000, -200]
    assert result.warnings == []


def test_year_cannot_contradict_printed_short_period():
    with pytest.raises(ParseError, match="year conflicts"):
        parse_pdf(card_pdf(), statement_year=2025, **{**OPTIONS, "convention": "card"})


@pytest.mark.parametrize(
    "options,pattern",
    [
        ({"extra_period": True}, "Multiple statement periods"),
        ({"malformed_date": True}, "unreadable transaction"),
    ],
)
def test_conflicting_periods_and_malformed_dates_abort_pdf(options, pattern):
    with pytest.raises(ParseError, match=pattern):
        parse_pdf(card_pdf(**options), statement_year=2026, **{**OPTIONS, "convention": "card"})


def test_year_setting_flows_through_actual_upload_api(tmp_path):
    with TestClient(create_app(str(tmp_path / "test.db"))) as client:
        params = {"convention": "card", "statement_year": 2026}
        rejected = client.post(
            "/api/statements",
            params={**params, "statement_year": 2200},
            files={"file": ("fictional.pdf", card_pdf())},
        )
        assert rejected.status_code == 422
        response = client.post(
            "/api/statements", params=params, files={"file": ("fictional.pdf", card_pdf())}
        )
        assert response.status_code == 201
        state = client.get("/api/workspace").json()
        assert state["summary"]["total"] == 4
        assert state["summary"]["cash_in_minor"] == 11000
        assert state["summary"]["cash_out_minor"] == 1700
        assert state["summary"]["confirmed"]["income_minor"] == 0
