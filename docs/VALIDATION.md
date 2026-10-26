# Verification record

Verified locally on 26 October 2026, Windows, Python 3.13.12, Node 24.14.1.

| Check | Observed result |
| --- | --- |
| Python regression suite | **89 passed** |
| React production build | TypeScript strict checks and Vite build passed |
| Real browser workflow | **13 passed**, Chromium, approximately 17 seconds |
| Accessibility | No axe violations in tested empty workspace, populated workspace, review dialog and upload dialog |
| Mobile | 390px viewport, no page overflow; table scroll and transaction review verified |
| Keyboard | Modal Tab containment, Escape, and trigger focus restoration verified |
| Money precision | Large valid aggregate preserved every cent in the rendered UI; unsafe aggregate rejected atomically |
| Dependency audit | `npm audit --omit=dev`: zero reported vulnerabilities |
| Development runner | Both localhost services returned HTTP 200; runner shutdown completed |
| Single-server build | Built index, JavaScript asset, and Python health endpoint all returned HTTP 200 |
| Synthetic performance | 10,000-row import approximately 0.76s; workspace read approximately 0.48s |

The Python test client emits one upstream Starlette deprecation warning about its current httpx integration. Tests pass; no warning is suppressed. Browser tools emit a harmless terminal color-environment warning.

Commands and prerequisites are in the root README. Performance metadata is in [`benchmark.json`](benchmark.json); regression assertions cover behavior and accounting, rather than a machine-dependent timing threshold. Browser tests use temporary storage and fictional statements. The documented screenshots come from those tests.

Automated checks cover the tested layouts and cases, not universal accessibility or universal bank-format accuracy. PDF imports require comparison with their original documents. The CI workflow additionally declares Windows/Linux and Python 3.11/3.13 coverage; see GitHub Actions for the actual remote run status.
