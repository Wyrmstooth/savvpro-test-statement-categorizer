# AI usage

## Tools and scope

OpenAI Codex assisted implementation in this repository: reading the assessment, planning, Python and React development, fictional fixtures, tests, browser QA, documentation, and Git/GitHub operations. The Codex Sites skill supplied interface/accessibility guidance; delivery follows the assessment's GitHub workflow. No Sites project or external hosted runtime is required.

Codex used the local shell, GitHub CLI, FastAPI/pdfplumber primary documentation, Playwright/Chromium, axe, and local screenshots. All development occurred in a single agent; no external category model or classification API is used by the application. No real bank statements or real customer records were provided or committed.

## How AI helped

- Designed a deterministic evidence pipeline with explicit abstention, money-direction guards, merchant boundaries, user rules, and refund reconciliation.
- Implemented strict document ingestion, exact minor-unit arithmetic, atomic persistence, review audit history, exports, and a responsive interface.
- Authored regression cases and ran the actual API and browser workflows; inspected screenshot artifacts.
- Iterated against observed failures, rather than accepting the first generated code as correct.

## Where the first drafts were wrong

1. The initial frontend dependency choice used `@vitejs/plugin-react: latest` with Vite 7. npm correctly rejected its newer incompatible peer requirement. The plugin was pinned to a compatible major and a lockfile committed; no peer checks were bypassed.
2. The first pass used text that was too pale and small. axe exposed contrast failures. Text colors and sizes were corrected, visible labels and accessible names were aligned, and the checks were kept in the browser suite.
3. Native dialog behavior alone was insufficient to keep all Tab navigation inside the modal in Chromium. An explicit focus loop was added, including exclusion of controls hidden inside closed details; Escape and focus restoration are tested.
4. A screen-reader-only table label escaped the mobile scroll container because it lacked a positioned ancestor. Browser measurements found page overflow. Positioning the scroll container fixed it while preserving horizontal table scrolling.
5. Early financial logic inverted explicit `CR` / `DR` values under the positive-charge card convention and could accept contradictory refund wording after a merchant match. These precedence errors were fixed and regression-tested.
6. The first normalization removed every long number, which could collapse distinct merchants. Unlabeled digits are now preserved, and broad retailers cannot borrow software-brand keywords to obtain a confident category.

The resulting software is still bounded: synthetic tests do not establish universal statement accuracy, and PDF extraction must be reconciled. See `DESIGN.md`.

## Follow-up: review remediation

The submitted review correctly identified eight gaps in the earlier implementation: empty merchant identities, backdated refund capacity, unchecked export currency, permissive money cleanup, invalid batch versions, skip-link routing, hidden mobile navigation and retained batch category state. Codex traced and fixed these, added transactional refund allocations and startup identity migrations, and tested changes to the supporting purchases as well as concurrent refunds. OWASP's primary CSV-injection guidance informed the expanded free-text export tests; spreadsheet behavior remains a documented limitation.

Browser testing caught an invalid `dialog` role on an `aside` in the first drawer fix. The container now uses valid dialog/complementary semantics, with tested inert state, focus containment and restoration. The updated suite has 202 backend and 20 browser cases; the external comparison still passes all 10 checks. See [REVIEW_FIXES.md](docs/REVIEW_FIXES.md) for the concrete remediation record. No classification model was introduced.

The sanitized [review-fixes-token-log.json](docs/ai-usage/review-fixes-token-log.json) snapshot was captured at `2026-10-26T15:05:21.999283+00:00`. Its cumulative client total is 27,279,038 tokens, predominantly repeated cached input. Additional counts since the external-validation snapshot are below; subsequent documentation, CI monitoring and final reporting are excluded.

| Counter | Additional tokens since external-validation snapshot |
| --- | ---: |
| Input (including cached) | 8,949,394 |
| Cached input (subset) | 8,876,416 |
| Output | 67,152 |
| Reasoning (output subset) | 41,793 |
| Input + output total | 9,016,546 |

## Actual token evidence

[`docs/ai-usage/token-log.json`](docs/ai-usage/token-log.json) contains a sanitized snapshot of the local Codex client's actual `token_count` events. It records timestamps, token counters, and the model identifier if the client exposes it. It excludes prompts, tool payloads, local paths, account information, and credentials.

The summary field **`usage_during_recorded_calls`** is the measured usage through the final captured event. Input tokens include repeated context and cached input; cached tokens are a subset, rather than another amount to add. Reasoning tokens are reported separately as a subset of output. These are client-reported counts, not a billing estimate. Calls after the stated capture cutoff, including final submission, are not included; no final-total figure is fabricated.

The export can be reproduced locally with:

```text
python scripts/export_ai_usage.py <local-codex-session.jsonl>
```

The allowlist exporter has a regression test verifying that conversation content and credential-like fields cannot leak into the artifact. Raw Codex logs must not be committed.

## Follow-up: independently published statement testing

At the user's request, Codex located an official Capital One demonstration PDF and independent fictional checking/card statement files, ran them through isolated real API instances, and compared extracted dates, descriptions and amounts across PDF/CSV representations. Original downloads stayed outside the repository. The previous committed implementation was rerun in a separate temporary process against the same pinned inputs; results are recorded in `docs/external-validation.json`.

This exposed assumptions the initial synthetic tests had missed: conflicting bank export headers, verified summary rows, borderless tables, omitted years, opposite PDF/CSV sign conventions, and refund/payout precedence. Fixes were made in original Python code and supported by authored fictional regression cases. The browser suite now checks the actual PDF year-setting flow. The report explicitly preserves unsupported layouts and low category coverage instead of treating successful extraction as accurate automatic categorization. No external model categorized the transactions.

## Recorded snapshot

Client-reported model: `gpt-6.1-sol`. Captured at `2026-10-26T13:47:58.616176+00:00`.

| Counter | Tokens |
| --- | ---: |
| Input (including cached) | 6,279,089 |
| Cached input (subset) | 6,186,624 |
| Output | 102,746 |
| Reasoning output (subset) | 25,080 |
| Total input + output | 6,381,835 |

## Follow-up token evidence

The follow-up snapshot is [external-validation-token-log.json](docs/ai-usage/external-validation-token-log.json), captured at `2026-10-26T14:24:10.760393+00:00`. It retains cumulative client counters. Additional counts since the initial submission snapshot are below; later PR updates and final reporting are excluded.

| Counter | Additional tokens since initial snapshot |
| --- | ---: |
| Input (including cached) | 11,820,127 |
| Cached input (subset) | 11,724,160 |
| Output | 60,530 |
| Reasoning (output subset) | 30,645 |
| Input + output total | 11,880,657 |
