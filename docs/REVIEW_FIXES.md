# Review remediation

Verified 26 October 2026. Engine version: **1.2.0**. This records the eight findings from the submitted review and related failures found while tracing them.

| Finding | Result | Regression evidence |
| --- | --- | --- |
| Empty merchant keys match unrelated refunds | Preserve Unicode letters/digits; require a nonempty exact identity for contextual matches and learned rules. Unrelated non-Latin names remain distinct. | `test_unrelated_non_latin_merchants_cannot_share_refund_capacity`, `test_empty_symbol_only_keys_never_enable_automatic_refunds`, `test_same_non_latin_identity_can_match_and_learn_exactly` |
| Backdated refunds reuse spending already consumed by later refunds | Persist exact purchase/refund allocations under the write lock. Existing matches reserve before new backdated candidates; future purchases cannot fund past refunds. | `test_backdated_refund_cannot_reuse_a_later_refunds_allocation`, `test_concurrent_refund_imports_cannot_double_reserve_one_purchase`, `test_future_purchases_cannot_fund_a_backdated_refund` |
| Currency query permits formulas in summary exports/filenames | Use the supported currency literal type on import, workspace and export endpoints. Invalid values return 422 before output is generated. | `test_currency_query_is_allowlisted_before_read_or_export`, `test_valid_summary_currency_is_literal_and_filename_safe` |
| Money parsing rewrites malformed symbols into valid numbers | Parse a complete amount grammar with at most one prefix/sign and validated grouping. Reject embedded/repeated symbols and contradictory signs. | `test_malformed_money_is_not_rewritten`, `test_supported_money_forms_preserve_cents_and_direction`, `test_malformed_amount_aborts_whole_upload` |
| Nonpositive batch versions cause 500 | Validate typed batch items before entering the write transaction. Strict positive integers and canonical IDs are required. A failed batch changes no rows. | `test_bad_batch_version_returns_422_and_is_atomic` |
| Skip link resets the hash route | Prevent hash navigation and focus the main element without clearing view state. | Browser: `skip link focuses content without changing the current route or filters` |
| Hidden mobile sidebar stays keyboard/screen-reader accessible | Closed drawer is inert and hidden from accessibility APIs; open drawer traps focus, closes on Escape, and restores the visible trigger. Desktop navigation remains available after resize. | Browser: `closed mobile navigation is inert, open navigation traps focus, desktop remains available`; axe on open drawer |
| Retained income choice leaks into a debit batch | Derive one eligible category used by both the displayed select and POST payload; reject empty/stale/oversized selections. | Browser: `credits-only income choice cannot leak into the next debit batch` |

Backend cases live in [`test_input_boundaries.py`](../backend/tests/test_input_boundaries.py) and [`test_refund_allocations.py`](../backend/tests/test_refund_allocations.py). Browser cases live in [`workspace.spec.ts`](../frontend/e2e/workspace.spec.ts).

## Related edge cases

- Deleting, excluding or recategorizing a supporting purchase revalidates its automatic refund, increases the dependent row's version and records an audit event. A stale edit returns 409. Removing/excluding a refund releases capacity. Partial refunds across multiple purchases preserve every cent.
- Existing oversubscribed automatic matches are repaired on startup. Old collapsed Unicode identities are recalculated. Ambiguous learned rules are retained, disabled and labeled for confirmation; subsequent restarts do not reactivate them. Explicit human decisions remain intact. Migrations also support the original rules schema.
- CR/DR inside accounting parentheses is not inverted again for card statements. Currency markers in balances and totals must agree with the statement. Recognized zero-valued balance metadata is skipped, while actual zero transactions remain visible. Oversized CSV header fields return a validation error rather than a server error.
- Free-text CSV formula detection includes leading controls and Unicode compatibility variants; numeric money fields stay numeric. Currency is allowlisted separately. Apostrophe escaping addresses the tested attack forms; spreadsheet import and save/reopen behavior varies, so it is not a universal guarantee across spreadsheet software. See [OWASP CSV Injection](https://community.owasp.org/attacks/CSV_Injection).
- The search shortcut focuses its field after route rendering. Opening Help from mobile navigation closes the drawer first and restores focus to a visible target when Help closes. The review history shows automatic returns to review.

## Verification and boundaries

- **202 backend tests passed**, including concurrent imports, atomic failure, migration restarts, allocations and audit/version changes.
- **20 Chromium browser tests passed**, using the actual Python API and isolated fictional data; axe covers the tested dialogs and mobile drawer.
- Strict TypeScript production build and Python Ruff checks passed.
- **10/10 external validation checks passed**, retaining the same six pinned public inputs and original-commit comparison. See [EXTERNAL_VALIDATION.md](EXTERNAL_VALIDATION.md) for sources and remaining category-coverage limits.
- The 10,000-row synthetic import took **0.7297s**, with **0.4278s** for a workspace read on the recorded local machine. [Measured metadata](review-benchmark.json) is a throughput observation, not an accuracy result or SLA.

Automatic contextual refunds require imported eligible purchases. Known-merchant and manually confirmed refunds may refer to an unimported purchase; their explicit category decisions remain authoritative. The application retains its documented single-user and bounded-PDF scope.
