"""Fictional reproductions of format problems found during external sample testing."""

import pytest

from app.engine import decide, merchant_key, resolve_refund
from app.parser import ParseError, parse_csv

OPTIONS = {"currency": "USD", "date_order": "mdy", "convention": "bank"}


@pytest.mark.parametrize(
    "description",
    [
        "STRIPE PAYOUT REFUND",
        "CLIENT PAYMENT REVERSAL",
        "SQUARE PAYOUT RETURNED",
    ],
)
def test_refund_evidence_cannot_become_client_income(description):
    decision = decide(description, 12500)
    assert decision.needs_review
    assert decision.category != "income"
    assert decision.flow == "refund"


def test_history_cannot_override_a_mandatory_payout_refund_conflict():
    decision = decide("CLIENT PAYMENT REFUND", 1000)
    originals = [{"id": "original", "category": "office", "amount_minor": -5000}]
    assert resolve_refund(decision, 1000, originals, 0) == decision


@pytest.mark.parametrize("word", ["REFUND", "REFUNDED", "REVERSAL", "REVERSED", "RETURN", "RETURNED"])
def test_refund_word_variants_obey_direction_and_normalize_consistently(word):
    assert decide(f"ADOBE {word}", -1000).needs_review
    assert decide(f"ADOBE {word}", 1000).flow == "refund"
    assert merchant_key(f"ADOBE {word}") == "ADOBE"


def test_export_with_details_and_memo_keeps_actual_description():
    text = (
        "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
        "DEBIT,10/01/2026,ADOBE CREATIVE CLOUD,-59.99,DEBIT_CARD,1000.00,"
    )
    rows = parse_csv(text.encode(), **OPTIONS).rows
    assert len(rows) == 1
    assert rows[0].description == "ADOBE CREATIVE CLOUD"
    assert rows[0].amount_minor == -5999


def test_transaction_date_precedes_posting_date_and_description_precedes_memo():
    text = (
        "Transaction Date,Post Date,Posting Date,Description,Category,Type,Amount,Memo\n"
        "10/01/2026,10/03/2026,10/03/2026,FIGMA,Other,Sale,-15.00,Reference only"
    )
    row = parse_csv(text.encode(), **OPTIONS).rows[0]
    assert row.date == "2026-10-01"
    assert row.description == "FIGMA"


def test_duplicate_identical_primary_headers_still_fail():
    with pytest.raises(ParseError, match="Multiple description"):
        parse_csv(b"Date,Description,Description,Amount\n2026-10-01,FIGMA,ADOBE,-15", **OPTIONS)


def test_wrong_card_sign_setting_is_caught_by_explicit_sale_type():
    text = b"Date,Description,Type,Amount\n2026-10-01,FIGMA,Sale,-15.00"
    with pytest.raises(ParseError, match="sign conflicts"):
        parse_csv(text, **{**OPTIONS, "convention": "card"})


def test_signed_card_csv_does_not_need_its_signs_flipped():
    text = (
        "Transaction Date,Post Date,Description,Type,Amount\n"
        "10/01/2026,10/02/2026,FIGMA,Sale,-15.00\n"
        "10/03/2026,10/04/2026,FIGMA REFUND,Return,5.00"
    )
    rows = parse_csv(text.encode(), **OPTIONS).rows
    assert [r.amount_minor for r in rows] == [-1500, 500]


def test_opening_balance_and_totals_are_verified_metadata_not_transactions():
    text = (
        "Fictional Example Bank\nDate,Description,Debit,Credit,Balance\n"
        "10/01/2026,Beginning balance,,,100.00\n"
        "10/02/2026,FIGMA,15.00,,85.00\n"
        "10/03/2026,CLIENT PAYMENT,,50.00,135.00\n"
        ",Totals,15.00,50.00,"
    )
    rows = parse_csv(text.encode(), **OPTIONS).rows
    assert len(rows) == 2
    assert sum(r.amount_minor for r in rows) == 3500
    with pytest.raises(ParseError, match="Running balance"):
        parse_csv(text.replace("85.00", "86.00").encode(), **OPTIONS)
    with pytest.raises(ParseError, match="Declared debit/credit totals"):
        parse_csv(text.replace(",Totals,15.00,50.00,", ",Totals,14.00,50.00,").encode(), **OPTIONS)


def test_closing_balance_is_verified_and_cannot_hide_more_transactions():
    text = (
        "Date,Description,Debit,Credit,Balance\n"
        "10/01/2026,Opening balance,,,100.00\n"
        "10/02/2026,FIGMA,15.00,,85.00\n"
        "10/03/2026,Closing balance,,,85.00"
    )
    assert len(parse_csv(text.encode(), **OPTIONS).rows) == 1
    with pytest.raises(ParseError, match="Closing balance"):
        parse_csv(text.replace("Closing balance,,,85.00", "Closing balance,,,84.00").encode(), **OPTIONS)
    with pytest.raises(ParseError, match="after a closing balance"):
        parse_csv((text + "\n10/04/2026,NOTION,10.00,,75.00").encode(), **OPTIONS)


def test_utf16_spreadsheet_export_has_explicit_bom_support():
    text = "Date,Description,Amount\n2026-10-01,FIGMA,-15.00"
    assert parse_csv(text.encode("utf-16"), **OPTIONS).rows[0].amount_minor == -1500


def test_space_after_sign_is_not_ambiguous_grouping():
    text = "Date,Description,Amount\n2026-10-01,MONTHLY SERVICE FEE,- 12.00"
    assert parse_csv(text.encode(), **OPTIONS).rows[0].amount_minor == -1200


def test_starred_accounting_headers_work_without_trusting_external_categories():
    text = "*Date,*Amount,Payee,Description,Category\n2026/10/01,-15.00,Vendor,FIGMA,Income"
    row = parse_csv(text.encode(), **OPTIONS).rows[0]
    assert row.description == "FIGMA"
    assert decide(row.description, row.amount_minor).category == "software"
