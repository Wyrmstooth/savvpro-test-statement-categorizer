# Verification record

Verified locally on 26 October 2026, Windows, Python 3.13.12, Node 24.14.1.

| Check | Observed result |
| --- | --- |
| Python regression suite | **202 passed** |
| React production build | TypeScript strict checks and Vite build passed |
| Real browser workflow | **20 passed**, Chromium |
| Accessibility | No axe violations in tested empty workspace, populated workspace, review dialog, upload dialog and open mobile navigation |
| Mobile | 390px viewport, no page overflow; table scroll and transaction review verified |
| Keyboard | Dialog/drawer Tab containment, hidden-drawer isolation, skip-link route preservation, search shortcut, Escape, and visible trigger focus restoration verified |
| Money precision | Large valid aggregate preserved every cent in the rendered UI; unsafe aggregate rejected atomically |
| Dependency audit | `npm audit --omit=dev`: zero reported vulnerabilities |
| Development runner | Both localhost services returned HTTP 200; runner shutdown completed |
| Single-server build | Built index, JavaScript asset, and Python health endpoint all returned HTTP 200 |
| Synthetic performance | 10,000-row import 0.7297s; workspace read 0.4278s |
| Python lint | `ruff check backend scripts`: all checks passed |
| Review regressions | Exact refund reservations, backdated/concurrent imports, purchase dependencies, legacy migrations, strict money/currency/version inputs, formula variants and batch selection passed |

The Python test client emits one upstream Starlette deprecation warning about its current httpx integration. Tests pass; no warning is suppressed. Browser tools emit a harmless terminal color-environment warning.

Commands and prerequisites are in the root README. Current performance metadata is in [`review-benchmark.json`](review-benchmark.json); [`benchmark.json`](benchmark.json) retains the earlier observation. Regression assertions cover behavior and accounting, rather than a machine-dependent timing threshold. Browser tests use temporary storage and fictional statements. The documented screenshots come from those tests. [REVIEW_FIXES.md](REVIEW_FIXES.md) maps all eight review findings to their fixes and coverage.

Automated checks cover the tested layouts and cases, not universal accessibility or universal bank-format accuracy. PDF imports require comparison with their original documents. The CI workflow additionally declares Windows/Linux and Python 3.11/3.13 coverage; see GitHub Actions for the actual remote run status.

Follow-up external validation: 10/10 checks passed against six public source files, compared with 2/10 for original commit a9aa30f. Five valid PDF/CSV formats match the independently expected row counts and cash totals. See [EXTERNAL_VALIDATION.md](EXTERNAL_VALIDATION.md) for sources, settings, coverage limitations, and the reproducible report.
