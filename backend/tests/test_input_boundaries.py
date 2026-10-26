import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.parser import ParseError, money, parse_csv

OPTIONS = {"currency": "USD", "date_order": "mdy", "convention": "bank"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "bounds.db"))) as value:
        yield value


@pytest.mark.parametrize(
    "value",
    [
        "1$2.34",
        "$$12.34",
        "$£12.34",
        "USD $12.34",
        "12.34$",
        "1€2.34",
        "--12.34",
        "-$-12.34",
        "(-12.34)",
        "-12.34 CR",
        "+12.34 DR",
    ],
)
def test_malformed_money_is_not_rewritten(value):
    with pytest.raises(ParseError):
        money(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("-$12.34", -1234),
        ("$-12.34", -1234),
        ("- USD 12.34", -1234),
        ("(USD 12.34)", -1234),
        ("($12.34)", -1234),
        ("−$12.34", -1234),
        ("12.34 CR", 1234),
        ("($12.34 DR)", -1234),
        ("- 12.34", -1234),
    ],
)
def test_supported_money_forms_preserve_cents_and_direction(value, expected):
    assert money(value) == expected


def test_currency_markers_in_balances_are_not_ignored():
    text = "Date,Description,Debit,Credit,Balance\n2026-01-01,Opening balance,,,£100.00"
    with pytest.raises(ParseError, match="currency conflicts"):
        parse_csv(text.encode(), **OPTIONS)


def test_currency_in_totals_must_agree_with_transaction_currency():
    text = "Date,Description,Debit,Credit,Currency\n2026-01-01,FIGMA,15.00,,USD\n,Totals,15.00,0,GBP"
    with pytest.raises(ParseError, match="Mixed currencies"):
        parse_csv(text.encode(), **OPTIONS)


def test_zero_balance_metadata_is_not_imported_as_a_transaction():
    text = (
        "Date,Description,Debit,Credit,Balance\n2026-01-01,Opening balance,0.00,0.00,100.00\n"
        "2026-01-02,FIGMA,15.00,,85.00\n2026-01-03,Closing balance,0,0,85.00"
    )
    rows = parse_csv(text.encode(), **OPTIONS).rows
    assert len(rows) == 1 and rows[0].amount_minor == -1500


def test_card_direction_inside_parentheses_is_not_inverted_again():
    rows = parse_csv(
        b"Date,Description,Amount\n2026-01-01,FIGMA,($12.34 DR)", **{**OPTIONS, "convention": "card"}
    ).rows
    assert rows[0].amount_minor == -1234


@pytest.mark.parametrize("path", ["/api/workspace", "/api/export?kind=summary", "/api/export"])
@pytest.mark.parametrize(
    "currency", ["=1+1", "@SUM(1)", 'USD"\r\nInjected: yes', "USD,GBP", "usd", "", "XYZ"]
)
def test_currency_query_is_allowlisted_before_read_or_export(client, path, currency):
    separator = "&" if "?" in path else "?"
    result = client.get(f"{path}{separator}", params={"currency": currency})
    assert result.status_code == 422
    assert "content-disposition" not in result.headers


@pytest.mark.parametrize("version", [0, -1, True, False, 1.0, "1", None])
def test_bad_batch_version_returns_422_and_is_atomic(client, version):
    client.post("/api/demo")
    rows = client.get("/api/workspace").json()["transactions"][:2]
    result = client.post(
        "/api/review-batch",
        json={
            "category": "office",
            "items": [
                {"id": rows[0]["id"], "version": rows[0]["version"]},
                {"id": rows[1]["id"], "version": version},
            ],
        },
    )
    assert result.status_code == 422
    fresh = client.get("/api/workspace").json()["transactions"][:2]
    assert [r["version"] for r in fresh] == [r["version"] for r in rows]


def test_oversized_csv_header_fails_as_input_error_not_server_error(client):
    content = "x" * 150000 + "\nDate,Description,Amount\n2026-01-01,FIGMA,-15"
    response = client.post("/api/statements", files={"file": ("bad.csv", content)})
    assert response.status_code == 422
    assert client.get("/api/workspace").json()["statements"] == []


def test_malformed_amount_aborts_whole_upload(client):
    content = "Date,Description,Amount\n2026-01-01,FIGMA,-15\n2026-01-02,ADOBE,1$2.34"
    response = client.post("/api/statements", files={"file": ("bad.csv", content)})
    assert response.status_code == 422
    assert client.get("/api/workspace").json()["statements"] == []


def test_valid_summary_currency_is_literal_and_filename_safe(client):
    response = client.get("/api/export", params={"kind": "summary", "currency": "GBP"})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert all(row["Currency"] == "GBP" for row in rows)
    assert "folio-summary-GBP.csv" in response.headers["content-disposition"]


@pytest.mark.parametrize(
    "text", ["=1+1", "\t=1+1", "\n@SUM(1)", "\ufeff=1+1", "\u200b+1", "\uff1d1+1", " \uff20123"]
)
def test_export_formula_prefixes_and_unicode_variants_are_neutralized(client, text):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["Date", "Description", "Amount"])
    writer.writerow(["2026-01-01", text, "-10.00"])
    response = client.post("/api/statements", files={"file": ("test.csv", stream.getvalue())})
    assert response.status_code == 201
    exported = client.get("/api/export").content.decode("utf-8-sig")
    row = next(csv.DictReader(io.StringIO(exported)))
    assert row["Description"].startswith("'")
    assert row["Amount"] == "-10.00"
