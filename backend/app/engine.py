"""Original deterministic decision engine. No model, network call or fuzzy auto-accept."""

import re
import unicodedata
from dataclasses import dataclass, field

CATEGORIES = {
    "software": {"name": "Software & subscriptions", "color": "#768bcb"},
    "travel": {"name": "Travel & transport", "color": "#85b4aa"},
    "office": {"name": "Office & supplies", "color": "#d6ae74"},
    "marketing": {"name": "Marketing & advertising", "color": "#b69bc8"},
    "professional": {"name": "Professional services", "color": "#95a874"},
    "meals": {"name": "Meals & coffee", "color": "#d4917e"},
    "fees": {"name": "Bank & processing fees", "color": "#a7a1b5"},
    "income": {"name": "Client income", "color": "#4b8066"},
    "transfer": {"name": "Transfers & payments", "color": "#8e9ba5"},
    "personal": {"name": "Personal", "color": "#a8a9a2"},
    "uncategorized": {"name": "Uncategorized", "color": "#c5a86b"},
}
EXPENSE_CATEGORIES = set(CATEGORIES) - {"income", "transfer", "personal", "uncategorized"}
ENGINE_VERSION = "1.2.0"
REFUND_WORDS = r"REFUND(?:ED)?|REVERS(?:AL|ED)|RETURN(?:ED)?"
REFUND = re.compile(rf"\b(?:{REFUND_WORDS})\b")


@dataclass(frozen=True)
class Decision:
    category: str
    flow: str
    confidence: int
    needs_review: bool
    reasons: list[str]
    source: str = "engine"
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    pattern: str
    score: int = 97
    review: bool = False


# Word boundaries are essential: UBER EATS is not an Uber ride, and SHELLY is not SHELL.
RULES = (
    Rule("software.adobe", "software", r"\bADOBE(?:\s|$)"),
    Rule("software.figma", "software", r"\bFIGMA\b"),
    Rule("software.github", "software", r"\bGITHUB\b"),
    Rule("software.notion", "software", r"\bNOTION(?:\s+LABS)?\b"),
    Rule("software.dropbox", "software", r"\bDROPBOX\b"),
    Rule("software.google-workspace", "software", r"\bGOOGLE\s+(?:WORKSPACE|GSUITE|CLOUD)\b"),
    Rule("software.microsoft", "software", r"\bMICROSOFT\s+(?:365|AZURE)\b"),
    Rule("software.canva", "software", r"\bCANVA\b"),
    Rule("software.webflow", "software", r"\bWEBFLOW\b"),
    Rule("software.slack", "software", r"\bSLACK\b"),
    Rule("software.zoom", "software", r"\bZOOM\s+(?:US|VIDEO)\b"),
    Rule("travel.uber", "travel", r"\bUBER\s+(?:TRIP|RIDE)\b"),
    Rule("travel.lyft", "travel", r"\bLYFT\s+(?:RIDE|TRIP)\b"),
    Rule("travel.rail", "travel", r"\b(?:AMTRAK|TRAINLINE)\b"),
    Rule("office.supplies", "office", r"\b(?:OFFICE\s+DEPOT|STAPLES)\b"),
    Rule("marketing.google", "marketing", r"\bGOOGLE\s+ADS\b"),
    Rule("marketing.meta", "marketing", r"\b(?:META|FACEBOOK)\s+ADS\b"),
    Rule("professional.accounting", "professional", r"\b(?:ACCOUNTING|BOOKKEEPING)\s+(?:SERVICE|SERVICES)\b"),
    Rule("fees.bank", "fees", r"\b(?:MONTHLY\s+(?:BANK|SERVICE)\s+FEE|WIRE\s+FEE|OVERDRAFT\s+FEE)\b"),
    Rule("fees.processing", "fees", r"\b(?:STRIPE|PAYPAL)\s+(?:PROCESSING\s+)?FEE\b"),
    Rule("meals.delivery", "meals", r"\b(?:UBER\s+EATS|DOORDASH|GRUBHUB)\b", 75, True),
    Rule("meals.coffee", "meals", r"\b(?:STARBUCKS|CAFE|COFFEE|RESTAURANT)\b", 65, True),
)
COMPILED_RULES = tuple((rule, re.compile(rule.pattern)) for rule in RULES)
TRANSFER = re.compile(
    r"\b(?:TRANSFER\s+(?:TO|FROM)\s+(?:SAVINGS|CHECKING|OWN\s+ACCOUNT)|"
    r"INTERNAL\s+TRANSFER|CREDIT\s+CARD\s+(?:AUTO\s+)?PAYMENT|PAYMENT\s+THANK\s+YOU)\b"
)
PAYOUT = re.compile(r"\b(?:STRIPE|SQUARE|PAYPAL)\s+PAYOUT\b|\bCLIENT\s+(?:PAYMENT|INVOICE)\b")
BROAD_RETAILER = re.compile(r"^(?:AMAZON|AMZN|APPLE(?:\s+COM)?|WALMART|TARGET|COSTCO|EBAY|ETSY)\b")


def normalized_text(description: str) -> str:
    text = unicodedata.normalize("NFKD", description).upper()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join("".join(char if char.isalnum() else " " for char in text).split())


def merchant_key(description: str) -> str:
    """Remove known bank wrappers and labeled references; preserve all other digits."""
    text = normalized_text(description)
    text = re.sub(r"^(?:(?:POS|DEBIT CARD|CREDIT CARD|PURCHASE|SQ|TST) )+", "", text)
    text = re.sub(r"\b(?:REF|AUTH|REFERENCE)\s+\w+\b", "", text)
    text = REFUND.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def resolve_refund(
    decision: Decision, amount_minor: int, candidates: list[dict], refunded_minor: int
) -> Decision:
    """Resolve an explicit unknown refund only against unambiguous, accepted earlier spending.

    The caller restricts candidates to the exact merchant, currency and earlier dates.
    A shared category can resolve partial refunds; competing categories or excess value abstain.
    """
    if decision.category != "uncategorized" or decision.flow != "refund" or amount_minor <= 0:
        return decision
    if "income.refund-conflict" in decision.evidence:
        return decision
    if not candidates:
        return decision
    categories = {row["category"] for row in candidates}
    if len(categories) != 1 or not categories <= EXPENSE_CATEGORIES:
        return Decision(
            "uncategorized",
            "refund",
            0,
            True,
            [
                "Earlier purchases at this merchant have different categories. "
                "Choose which expense this refund offsets."
            ],
            evidence=["refund.conflicting-originals"],
        )
    capacity = -sum(row["amount_minor"] for row in candidates) - refunded_minor
    if amount_minor > capacity:
        return Decision(
            "uncategorized",
            "refund",
            0,
            True,
            [
                "This refund exceeds the remaining accepted spending at this merchant. "
                "Check the original purchase."
            ],
            evidence=["refund.exceeds-originals"],
        )
    return Decision(
        next(iter(categories)),
        "refund",
        95,
        False,
        [
            "Explicit refund matched earlier accepted spending at the exact merchant, in the same currency.",
            "All eligible original purchases agree on the category; "
            "this reduces expenses rather than adding income.",
        ],
        source="context",
        evidence=[f"refund.original:{r['id']}" for r in candidates[:5]],
    )


def valid_category_flow(category: str, flow: str) -> bool:
    return category in CATEGORIES and (category != "income" or flow == "income")


def decide(description: str, amount_minor: int, learned: dict | None = None) -> Decision:
    text = normalized_text(description)
    key = merchant_key(description)
    base_flow = "expense" if amount_minor < 0 else "income"
    if amount_minor == 0:
        return Decision("uncategorized", "neutral", 0, True, ["Zero-value row needs confirmation."])

    refund_marker = bool(REFUND.search(text))
    if refund_marker and amount_minor < 0:
        return Decision(
            "uncategorized",
            "expense",
            0,
            True,
            ["Refund wording conflicts with an outgoing amount. Check the statement's sign convention."],
        )
    if refund_marker and PAYOUT.search(text):
        return Decision(
            "uncategorized",
            "refund",
            0,
            True,
            [
                "Refund or reversal wording conflicts with a payout or client payment. "
                "Confirm the money's purpose."
            ],
            evidence=["income.refund-conflict"],
        )

    # Explicit money movement wins over merchant and learned expense rules.
    if TRANSFER.search(text):
        return Decision(
            "transfer",
            "transfer",
            99,
            False,
            ["Explicit account transfer or card payment; excluded from income and spending."],
            evidence=["movement.explicit"],
        )
    if PAYOUT.search(text) and amount_minor > 0:
        return Decision(
            "income",
            "income",
            97,
            False,
            ["An explicit client payment or processor payout is money received."],
            evidence=["income.payout"],
        )

    matches = [rule for rule, pattern in COMPILED_RULES if pattern.search(text)]
    categories = {rule.category for rule in matches}
    flow = "refund" if amount_minor > 0 and (matches or refund_marker) else base_flow

    if key and learned and learned.get("merchant_key") == key and learned.get("direction") == base_flow:
        category = learned["category"]
        learned_flow = (
            "transfer"
            if category == "transfer"
            else ("income" if category == "income" else ("refund" if amount_minor > 0 else "expense"))
        )
        return Decision(
            category,
            learned_flow,
            100,
            False,
            ["Matches your exact merchant rule for this money direction."],
            source="rule",
            evidence=[f"user:{key}:{base_flow}"],
        )

    if BROAD_RETAILER.search(key):
        return Decision(
            "uncategorized",
            "refund" if refund_marker and amount_minor > 0 else base_flow,
            0,
            True,
            ["A broad retailer does not identify what was purchased. Your context is needed."],
            evidence=["merchant.broad-retailer"],
        )

    if len(categories) > 1:
        return Decision(
            "uncategorized",
            flow,
            0,
            True,
            ["The description contains conflicting category signals. Choose the correct category."],
            evidence=[r.id for r in matches],
        )
    if matches:
        best = max(matches, key=lambda rule: rule.score)
        reasons = [f"Matched {best.id.replace('.', ' / ').replace('-', ' ')}."]
        if best.review:
            reasons.append("Business purpose cannot be inferred from a merchant. Confirm this expense.")
        if flow == "refund":
            reasons.append(
                "Money returned by this merchant reduces this category's expenses; it is not income."
            )
        return Decision(
            best.category, flow, best.score, best.review, reasons, evidence=[r.id for r in matches]
        )

    if refund_marker and amount_minor > 0:
        return Decision(
            "uncategorized",
            "refund",
            0,
            True,
            ["Refund detected, but the original spending category is unknown."],
        )
    if amount_minor > 0:
        return Decision(
            "uncategorized",
            "income",
            0,
            True,
            ["Unexplained credit: it could be income, a refund, or a transfer."],
        )
    return Decision(
        "uncategorized",
        "expense",
        0,
        True,
        ["No specific merchant evidence. Broad retailers and payment intermediaries need your context."],
    )
