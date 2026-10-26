import pytest

from app.engine import decide, merchant_key, resolve_refund


@pytest.mark.parametrize(
    "description,amount,category,flow,review",
    [
        ("ADOBE CREATIVE CLOUD", -5999, "software", "expense", False),
        ("POS FIGMA *PRO 82349203", -1500, "software", "expense", False),
        ("ADOBE REFUND", 1000, "software", "refund", False),
        ("UBER *TRIP", -1500, "travel", "expense", False),
        ("UBER EATS", -1500, "meals", "expense", True),
        ("UBER", -1500, "uncategorized", "expense", True),
        ("UBERMENSCH DESIGN", -1500, "uncategorized", "expense", True),
        ("SHELLY STUDIO", -1500, "uncategorized", "expense", True),
        ("AMAZON MKTPLACE", -1500, "uncategorized", "expense", True),
        ("APPLE.COM BILL", -1500, "uncategorized", "expense", True),
        ("PAYPAL *UNKNOWN", -1500, "uncategorized", "expense", True),
        ("JOES CAFE 9921", -1500, "meals", "expense", True),
        ("TRANSFER TO SAVINGS", -1500, "transfer", "transfer", False),
        ("TRANSFER FROM SAVINGS", 1500, "transfer", "transfer", False),
        ("CREDIT CARD PAYMENT", -1500, "transfer", "transfer", False),
        ("PAYMENT THANK YOU", 1500, "transfer", "transfer", False),
        ("BANK TRANSFER", 1500, "uncategorized", "income", True),
        ("STRIPE PAYOUT", 1500, "income", "income", False),
        ("STRIPE PROCESSING FEE", -1500, "fees", "expense", False),
        ("UNKNOWN DEPOSIT", 1500, "uncategorized", "income", True),
        ("UNKNOWN REFUND", 1500, "uncategorized", "refund", True),
        ("ADOBE REFUND", -1500, "uncategorized", "expense", True),
        ("ADOBE FIGMA", -1500, "software", "expense", False),
        ("ADOBE UBER TRIP", -1500, "uncategorized", "expense", True),
        ("GOOGLE ADS", -1500, "marketing", "expense", False),
        ("GOOGLE WORKSPACE", -1500, "software", "expense", False),
        ("GOOGLE", -1500, "uncategorized", "expense", True),
        ("NOTION", 0, "uncategorized", "neutral", True),
    ],
)
def test_decision_contract(description, amount, category, flow, review):
    decision = decide(description, amount)
    assert (decision.category, decision.flow, decision.needs_review) == (category, flow, review)
    assert decision.reasons
    assert 0 <= decision.confidence <= 100


def test_normalization_preserves_meaningful_digits():
    assert merchant_key("POS SQ *STUDIO 54 REF 12345678") == "STUDIO 54"
    assert merchant_key("MICROSOFT 365") != merchant_key("MICROSOFT")
    assert merchant_key("7 ELEVEN") != merchant_key("ELEVEN")
    assert merchant_key("STUDIO 123456") != merchant_key("STUDIO 123457")


def test_learned_rule_is_exact_and_directional():
    rule = {"merchant_key": "JOES CAFE 9921", "direction": "expense", "category": "personal"}
    assert decide("JOES CAFE 9921", -100, rule).category == "personal"
    assert decide("JOES CAFE 9922", -100, rule).needs_review
    assert decide("JOES CAFE 9921", 100, rule).needs_review


def test_transfer_guard_precedes_user_rule():
    rule = {"merchant_key": "TRANSFER TO SAVINGS", "direction": "expense", "category": "software"}
    assert decide("TRANSFER TO SAVINGS", -100, rule).category == "transfer"


def test_money_size_cannot_invent_category():
    for amount in (-1, -1000, -100000000):
        assert decide("UNKNOWN MERCHANT", amount).needs_review


def test_partial_refund_can_use_unambiguous_accepted_spending():
    decision = decide("PAPER AND INK REFUND", 500)
    originals = [{"id": "original", "category": "office", "amount_minor": -1000}]
    resolved = resolve_refund(decision, 500, originals, 0)
    assert resolved.category == "office"
    assert resolved.flow == "refund"
    assert resolved.source == "context"
    assert "refund.original:original" in resolved.evidence


def test_refund_linking_abstains_on_conflict_and_excess():
    decision = decide("PAPER AND INK REFUND", 500)
    originals = [{"id": "a", "category": "office", "amount_minor": -1000}]
    assert resolve_refund(decision, 500, originals, 600).needs_review
    originals.append({"id": "b", "category": "software", "amount_minor": -1000})
    assert resolve_refund(decision, 500, originals, 0).needs_review


def test_unexplained_credit_does_not_borrow_a_category_from_history():
    decision = decide("PAPER AND INK", 500)
    originals = [{"id": "a", "category": "office", "amount_minor": -1000}]
    assert resolve_refund(decision, 500, originals, 0) == decision


def test_broad_retailer_cannot_borrow_brand_keywords():
    assert decide("AMAZON ADOBE DESIGN BOOK", -2500).needs_review
    assert decide("APPLE FIGMA", -2500).needs_review
