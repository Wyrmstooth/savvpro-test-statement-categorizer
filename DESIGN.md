# Folio: design and decisions

## Customer and complete workflow

The customer is an independent creative freelancer: client payouts, design software, project travel, supplies, advertising, and occasional ambiguous personal/business purchases. A statement becomes categorized rows, a finite review queue, durable corrections, and an export for their bookkeeper. The app does not infer legal deductibility or impose a jurisdiction-specific tax schedule.

The interface uses a quiet sage palette, local typography, four useful totals, direct category exploration, and a transaction table. Explanations and implementation details live inside transaction details and Help. Upload settings make financial conventions explicit. Search, row selection, filters, sorting, pagination, exports, rules, and statement navigation operate on real persisted data.

## The brain is original code

`backend/app/engine.py` is a deterministic, network-free Python decision system. There is no LLM, embedding API, downloaded model, pretrained classifier, or external category service. `pdfplumber` extracts document structure; it makes no category decisions.

The decision function returns category, flow, heuristic evidence score, review flag, human-readable reasons, provenance, and stable rule identifiers. Scores are **ordinal rule strengths, not calibrated probabilities**. The UI says so. A high score never overrules a mandatory review condition.

### Decision order

1. **Validate and normalize.** Parse dates and exact decimal amounts before categorization. Store money in integer minor units. Preserve the original description and source row. Normalize Unicode, case, whitespace and punctuation for matching; remove only known payment wrappers and labeled authorization/reference tokens from merchant keys. Preserve unlabeled digits because a number can be part of a merchant's identity.
2. **Abstain on zero.** Zero-value rows remain visible and require confirmation.
3. **Protect money movement.** Specific descriptions such as `TRANSFER TO SAVINGS` or `CREDIT CARD PAYMENT` become transfers, excluded from spending and income. A vague `BANK TRANSFER` remains uncertain. Incoming explicit client payments or processor payouts become income; generic positive credits do not.
4. **Reject contradictory refund signs.** Outgoing transactions containing refund/reversal wording require review rather than quietly treating the wording as stronger than the amount.
5. **Apply an intentional user rule.** An explicitly remembered exact merchant key plus money direction can select a category for a future import. Explicit movement guards still take precedence. Rules do not silently recategorize older rows, apply across all merchants sharing one word, or learn from unconfirmed guesses.
6. **Protect broad retailers.** Amazon, Apple, and similar broad retailers require context, even if a description contains a software brand. A remembered exact rule can resolve one specific descriptor.
7. **Collect bounded merchant evidence.** Precompiled expressions identify specific vendors/products. Word boundaries stop substring collisions. `GOOGLE ADS` and `GOOGLE WORKSPACE` differ; `UBER TRIP` and `UBER EATS` differ; `UBER` alone is unresolved.
8. **Resolve or abstain.** Evidence agreeing on one category can be accepted. Competing categories stay in review. Meals always need business-purpose confirmation unless the user intentionally creates an exact rule. Unsupported merchants, vague intermediaries, and unexplained credits remain in review.
9. **Handle refunds as offsets.** A positive amount at an identified expense merchant is a category refund, never new client income. An explicit unknown refund can use earlier accepted spending only if its exact merchant and currency match, its original categories all agree, and its amount is within the remaining spending after previous refunds. Original transaction IDs are recorded as evidence. Future purchases, conflicting categories, and excess refunds cannot manufacture certainty.
10. **Apply import guards.** Possible duplicates and PDF reconciliation warnings force review regardless of merchant confidence or remembered rules.

The engine runs in linear time over descriptions with a fixed small rule set. Refund lookups use a merchant/currency/date index. Imports process purchases before refunds on the same date, independent of CSV row ordering. SQLite transactions atomically commit the entire statement and its decisions.

### Examples

| Description and signed amount | Decision | Why |
| --- | --- | --- |
| `ADOBE CREATIVE CLOUD`, −59.99 | Software / expense | Specific vendor evidence |
| `ADOBE REFUND`, +10.00 | Software / refund | Expense offset, not income |
| `ADOBE REFUND`, −10.00 | Needs review | Wording and money direction conflict |
| `UBER *TRIP`, −24.50 | Travel | Explicit ride descriptor |
| `UBER EATS`, −32.80 | Meals, needs review | Delivery is not transport; business purpose unknown |
| `JOES CAFE 9921`, −18.75 | Meals suggestion, needs review | Merchant type does not prove business purpose |
| `AMAZON ADOBE DESIGN BOOK`, −25.00 | Needs review | Retailer and product keyword do not establish category |
| `PAYPAL *MYSTERYDESIGN`, −64.00 | Needs review | Payment intermediary is not category evidence |
| `TRANSFER TO SAVINGS`, −1,000.00 | Transfer | Own-account movement |
| `STRIPE PAYOUT`, +4,200.00 | Client income | Explicit incoming settlement |
| `UNKNOWN DEPOSIT`, +250.00 | Needs review | Could be income, refund, or transfer |

## Financial invariants

- Decimal parsing and integer arithmetic end to end in Python, including export formatting. No float arithmetic in categorization, persistence, reconciliation, or CSV amounts. A per-currency bound on absolute movement keeps every API integer within JavaScript's exact range; the browser formats whole units and fractional cents with BigInt, including very large valid totals.
- Bank/card sign conventions are explicit. `CR` and `DR` carry their own direction. Separate Debit/Credit columns cannot both be nonzero. Missing amounts are rejected; actual zero is preserved.
- Every statement has one supported two-decimal currency. Currency markers must agree with the row/import currency. The all-statements workspace and exports are scoped to a single currency; no invented exchange rates.
- Included cash in minus included cash out equals net movement. Category signed totals sum to the same net. Excluding a duplicate removes it from every monetary total. Refunds offset expense categories, transfers never inflate client income.
- Headline totals use included rows with no outstanding review requirement. Category summaries expose both ready and provisional amounts and pending counts. Pending categories never quietly contribute to the headline spending/income figures.
- The same file hash cannot be imported twice. Across overlapping files, a date/original-description/amount/currency fingerprint flags new matches. Suspected duplicates stay visible because identical legitimate purchases exist. They cannot be batch-confirmed or create merchant rules.

## Persistence and review

SQLite uses foreign keys, WAL, parameterized SQL, and bounded transactions. A write lock covers import identity checks and insertion, eliminating duplicate-file races. Invalid rows abort CSV imports rather than silently producing incomplete books. Batch reviews roll back as a unit if any item is missing, invalid, or stale.

Each row has a version. PATCH and bulk review require the version the user saw; stale writes return 409. A manual decision records a before/after audit event, updates its note and inclusion flag, and can intentionally add or replace a narrowly scoped merchant rule. Audit history remains inspectable after refresh. Removing a statement cascades its transactions/history, releases its file identity for reimport, and retains independent merchant rules.

## Ingestion boundaries

CSV accepts common column aliases, a small bank preamble, three delimiters, two encodings, explicit date/decimal settings, accounting parentheses, grouped numbers, and credit/debit markers. Malformed grouping, excess decimal precision, impossible dates, ambiguous amount columns, invalid currencies, footer rows masquerading as transactions, and unequal column counts fail visibly with source-row diagnostics.

PDF extraction recognizes table headers and repeated page headers, with a conservative ISO-line fallback. It has file/page/row limits. OCR and universal layout inference are deliberately out of scope. Nontransaction pages create warnings and force review; unreadable transaction lines and scanned pages fail. A parser cannot prove that an arbitrary PDF layout contains no overlooked transaction: the interface and README require reconciliation with the original, and CSV is the recommended path.

## Security and local operation

The service is intentionally one local workspace, not a multi-tenant SaaS. Bind to loopback. Host validation blocks arbitrary DNS-rebinding hosts; origin checks reject cross-origin writes. File extensions, lengths, row counts, field sizes, signs, and review payloads are validated. Filenames are reduced to plain basenames. React renders descriptions as text. CSV free-text fields with spreadsheet formula prefixes are escaped while actual numeric amounts remain numeric. Upload bytes are not saved. Tests and committed samples use fictional data only.

The runtime makes no external classification/analytics requests. Fonts are served locally. A hosted version would need authentication, tenant-scoped storage/rules, encrypted backup policy, resource-isolated PDF workers, migrations, and stronger abuse controls. These are explicit boundaries, not implicit production claims.

## Validation and tradeoffs

Tests cover decision collisions, conservative abstention, sign conflicts, refund capacity/date/currency matching, financial reconciliation, malformed files, actual generated PDF extraction, duplicate behavior, atomic edits, concurrency versions, rule scope, export injection, statement removal, origin/host checks, and sanitized usage export. Browser tests use the real backend for import/review/rule/export flows, and check mobile overflow, focus trapping/restoration, and automated accessibility.

The sample is useful for demonstrating behavior; it is **not** evidence of broad real-bank accuracy. Merchant rules are curated for this customer and synthetic tests are regression checks, not a calibrated evaluation on unseen real statements. No percentage accuracy claim is made. Greater coverage should come from reviewed anonymized examples, measured precision/coverage, and additional tested parser adapters; fuzzy merchant matching should remain a suggestion until validated.

[`docs/benchmark.json`](docs/benchmark.json) records an actual synthetic 10,000-row import through the API and disposable SQLite database: approximately 0.76 seconds for import and 0.48 seconds for reading the workspace on the recorded Windows/Python environment. This is a local TestClient measurement, excluding browser rendering and real HTTP transport, not an accuracy result or service-level guarantee. Reproduce with `python scripts/benchmark.py` using the installed project environment.

## References consulted

- [FastAPI file upload documentation](https://fastapi.tiangolo.com/tutorial/request-files/) for multipart ingestion and `UploadFile` behavior.
- [pdfplumber primary documentation](https://github.com/jsvine/pdfplumber) for table/text extraction capabilities and limitations.
- Package manifests and actual installed tooling for dependency compatibility; integration tests determined the final supported behavior.

These informed ingestion mechanics. The decision rules, precedence, abstention, refund logic and accounting invariants are original project code.
