# External statement validation

Tested independently published files through the **actual upload API** on 26 October 2026. Each case used a fresh, disposable database; testing did not alter the user's local workspace.

The sources are an official bank demonstration statement and independently published fictional business statements. They exercise real document/export layouts without using private customer records. Original PDFs/CSVs remain outside this repository. Only hashes, source URLs, aggregate results, and fictional regression reproductions are committed.

## Observed results

| Published input | Expected rows | Money in | Money out | Before | After |
| --- | ---: | ---: | ---: | --- | --- |
| [Capital One savings sample PDF](https://ecm.capitalone.com/WCM/bank/pdfs/sample-estatement.pdf) | 3 | $7.24 | $0.00 | Unsupported | Exact match |
| [Independent checking PDF](https://getutilly.com/sample/bank.pdf) | 31 | $29,597.43 | $28,575.27 | Unsupported | Exact match |
| [Matching bank-style CSV](https://getutilly.com/sample/bank-csv.csv) | 31 | $29,597.43 | $28,575.27 | Opening/totals rows rejected | Exact match |
| [Independent card PDF](https://getutilly.com/sample/card.pdf) | 21 | $1,542.18 | $1,939.94 | Unsupported | Exact match |
| [Matching signed card CSV](https://getutilly.com/sample/card-csv.csv) | 21 | $1,542.18 | $1,939.94 | Exact match with negative-expense setting | Exact match; wrong-setting guard added |

The independent sample publisher also provides its expected totals and format descriptions on its [sample-file page](https://getutilly.com/guides/sample-bank-statement-files). Both PDF/CSV pairs now agree on **every extracted date, original description, signed amount, and currency**, irrespective of their row order. Opening/closing balances and declared debit/credit totals reconcile where supplied.

**10 of 10 external checks pass**, versus **2 of 10** when rerunning the same harness against original commit `a9aa30f`. The ten comprise five valid imports, one unsupported-guide control, two explicit-setting guards, and two PDF/CSV equivalence checks. The original version already supported the correctly configured signed card CSV and refused the unsupported guide; the report does not attribute those existing behaviors to the fixes.

The [Bank of America statement-reading guide](https://www.bankofamerica.com/content/documents/CG2/How%20To%20Read/en_US/HTR-043235.pdf) is an intentional negative control: it contains overlapping illustrative statement layouts and explanatory material. It remains **rejected**, with no transactions inserted. Refusing a guide is not evidence of supporting an actual complete Bank of America statement.

Machine-readable evidence, including hashes, settings, API statuses, pending counts, and the actual baseline rerun: [`external-validation.json`](external-validation.json).

## Problems fixed

- **Column aliases collided.** An export containing Description plus Details/Memo, or transaction plus posting dates, was rejected. The importer now applies documented semantic priority: transaction date before posting date, and Description before generic metadata. Identical duplicate headers still fail. A bank-provided Category never overrides the engine.
- **Summary rows looked like malformed transactions.** Explicit opening/closing balance rows and debit/credit totals can now be recognized and checked mathematically. Unknown footers still fail; incorrect running balances or totals abort the complete import.
- **Borderless tables were unreadable.** New bounded profiles use PDF word coordinates and printed column alignment. They distinguish withdrawals, deposits, amounts, and balances; handle repeated page headers; and validate complete opening/closing movement. Unreadable monetary lines and unsupported wrapped text are errors, not silently dropped rows.
- **Short dates had no trustworthy year.** Full printed statement periods now resolve omitted years, including December/January rollover. Where the printed period itself uses a two-digit year, the user must supply Statement year under Format details. No current-year or century guess is made.
- **Card PDF and CSV signs differ.** The card PDF uses positive charges; its CSV uses negative expenses. Explicit transaction Type evidence detects a contradictory setting, and the UI options now describe the sign rather than implying all credit-card exports use the same convention.
- **Payout wording overruled refunds.** A credit such as `STRIPE PAYOUT REFUND` or `CLIENT PAYMENT REVERSAL` could have become accepted client income. Refund conflicts now require review before payout rules, learned rules, or historical refund matching. Refunded/reversed/returned word variants follow the same checks.
- **Spreadsheet encoding and spacing.** BOM-marked UTF-16 exports and a bank-style space after a sign are supported without accepting malformed thousands grouping.

## Categorization findings

Import correctness and category coverage are different measurements:

| Unique statement | Accepted automatically | Needs review | Interpretation |
| --- | ---: | ---: | --- |
| Savings sample | 0 / 3 | 3 | Interest is not automatically called client income. |
| Business checking sample | 5 / 31 | 26 | Payroll, taxes, checks, vague deposits, and processor transfers need additional context/categories for this freelance-focused product. |
| Business card sample | 9 / 21 | 12 | Specific software, transport, office and payment descriptions are recognized; broad merchants and meal purpose remain uncertain. |

These samples do **not** establish a real-world category accuracy percentage. The checking fixture includes a broader employer business than the chosen freelance customer. Expanding payroll, tax, and other-income categories, plus reviewed merchant examples, would improve coverage. The system deliberately leaves unsupported business meaning pending rather than manufacture certainty. In particular, no savings interest or unexplained deposit was added to the headline client-income total.

## Reproduce

From an installed project environment (Windows command shown):

```powershell
.venv/Scripts/python scripts/validate_external_samples.py --download-dir ../statement-test-downloads --baseline-ref a9aa30f --output docs/external-validation.json
```

The first run downloads six public files. Subsequent runs can add `--offline` to use the reviewed cache. A changed publisher file fails its pinned hash instead of silently changing the evaluation. Downloads inside the repository are rejected. Baseline code is extracted into temporary storage, run in a separate Python process against the same files and dependencies, and removed afterwards.

The ordinary regression and browser suites use authored fictional reproductions, not network downloads, so CI remains independent of publisher availability.

## Try the downloaded files in Folio

| File | Amount setting | Extra setting |
| --- | --- | --- |
| `capital-one-sample.pdf` | Expenses are negative | USD; full dates are printed |
| `utilly-bank.pdf` or `utilly-bank.csv` | Expenses are negative | USD; month/day order |
| `utilly-card.pdf` | Charges are positive | USD; month/day; **Statement year 2026** |
| `utilly-card.csv` | Expenses are negative | USD; month/day order |

Import one representation of each statement unless intentionally testing duplicates. Importing both its PDF and CSV should flag matching transactions rather than silently count the same activity twice. Review or exclude those duplicates before treating totals as final.
