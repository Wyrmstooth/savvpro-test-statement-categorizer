"""Test independently published examples through the actual API, with optional before/after comparison.

Original downloads stay outside the repository. The report contains only source URLs,
hashes, aggregate counters and errors; no account holders, balances or transaction text.
Network access is opt-in by invoking this script, never part of CI's regression tests.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    {
        "file": "capital-one-sample.pdf",
        "publisher": "Capital One (official public sample)",
        "url": "https://ecm.capitalone.com/WCM/bank/pdfs/sample-estatement.pdf",
        "sha256": "453a0def3af36ada529c6fe324232fcc6221156081991f26060894ce89cc5e3b",
        "params": {"convention": "bank"},
        "expected": [3, 724, 0],
    },
    {
        "file": "utilly-bank.pdf",
        "publisher": "Utilly (independent fictional checking sample)",
        "url": "https://getutilly.com/sample/bank.pdf",
        "sha256": "738d015a58c7d4fab0bcb84bc2ecb496f7f4a954c1f51bcd7d9842e97526640e",
        "params": {"convention": "bank"},
        "expected": [31, 2959743, 2857527],
    },
    {
        "file": "utilly-card.pdf",
        "publisher": "Utilly (independent fictional card sample)",
        "url": "https://getutilly.com/sample/card.pdf",
        "sha256": "0217d5e0aad66456a02cfb8733cd7d347d5c17f01c4cdb890ff0d6baec46319f",
        "params": {"convention": "card", "statement_year": 2026},
        "expected": [21, 154218, 193994],
    },
    {
        "file": "utilly-bank.csv",
        "publisher": "Utilly (matching bank-style CSV)",
        "url": "https://getutilly.com/sample/bank-csv.csv",
        "sha256": "5a4ee566046fcb720700c8594028b66b7cf5f26ca7a6465a3f601dcfaa5e4c6d",
        "params": {"convention": "bank"},
        "expected": [31, 2959743, 2857527],
    },
    {
        "file": "utilly-card.csv",
        "publisher": "Utilly (matching signed card CSV)",
        "url": "https://getutilly.com/sample/card-csv.csv",
        "sha256": "b188b8424707860ca5db645736b466f6bca07c27c6bf3b90ab486f2c3b7a86d5",
        "params": {"convention": "bank"},
        "expected": [21, 154218, 193994],
    },
    {
        "file": "bofa-statement-guide.pdf",
        "publisher": "Bank of America (guide, negative control)",
        "url": "https://www.bankofamerica.com/content/documents/CG2/How%20To%20Read/en_US/HTR-043235.pdf",
        "sha256": "c4255bc5d9b30ac9d2edff29bb58cb4c538bd56d8ab2d91878ea2589472431d0",
        "params": {"convention": "bank"},
        "expected_status": 422,
    },
]


def download_sources(folder, offline):
    if folder.is_relative_to(ROOT):
        raise ValueError("Keep external downloads outside the repository.")
    folder.mkdir(parents=True, exist_ok=True)
    for source in SOURCES:
        path = folder / source["file"]
        if not path.exists():
            if offline:
                raise ValueError(f"Missing cached file: {source['file']}")
            request = urllib.request.Request(
                source["url"],
                headers={"User-Agent": "Mozilla/5.0 Folio-validation/1.0"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read(10 * 1024 * 1024 + 1)
            if hashlib.sha256(content).hexdigest() != source["sha256"]:
                raise ValueError(
                    f"Publisher changed {source['file']}; inspect it and update the reviewed manifest."
                )
            path.write_bytes(content)
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Hash mismatch in cached source {source['file']}")


def run_cases(folder):
    from app.main import create_app
    from fastapi.testclient import TestClient

    cases = [{**source, "id": source["file"]} for source in SOURCES]
    cases += [
        {
            **SOURCES[4],
            "id": "card-csv-wrong-sign-setting",
            "params": {"convention": "card"},
            "expected_status": 422,
            "error_contains": "sign",
        },
        {
            **SOURCES[2],
            "id": "card-pdf-missing-explicit-year",
            "params": {"convention": "card"},
            "expected_status": 422,
            "error_contains": "year",
        },
    ]
    results = []
    transactions = {}
    for case in cases:
        record = {
            key: case[key]
            for key in ("id", "file", "publisher", "url", "sha256", "params")
        }
        with (
            tempfile.TemporaryDirectory(prefix="folio-external-case-") as directory,
            TestClient(create_app(str(Path(directory) / "test.db"))) as client,
        ):
            response = client.post(
                "/api/statements",
                params=case["params"],
                files={
                    "file": (case["file"], (folder / case["file"]).read_bytes()),
                },
            )
            record["http_status"] = response.status_code
            state = client.get("/api/workspace").json()
            summary = state["summary"]
            if case.get("expected_status") == 422:
                detail = response.json().get("detail", "")
                record["error"] = detail
                passed = response.status_code == 422 and not state["statements"]
                passed &= case.get("error_contains", "").lower() in str(detail).lower()
                record["passed"] = passed
            else:
                expected = case["expected"]
                observed = [
                    summary["total"],
                    summary["cash_in_minor"],
                    summary["cash_out_minor"],
                ]
                record.update(
                    expected_rows_in_out_minor=expected,
                    observed_rows_in_out_minor=observed,
                )
                record["passed"] = response.status_code == 201 and observed == expected
                if response.status_code != 201:
                    record["error"] = response.json().get("detail")
                else:
                    record["review_count"] = summary["review_count"]
                    record["category_counts"] = dict(
                        Counter(r["category"] for r in state["transactions"])
                    )
                    record["warnings"] = response.json()["warnings"]
                    record["no_unresolved_credit_in_headline_income"] = summary[
                        "confirmed"
                    ]["income_minor"] == sum(
                        r["amount_minor"]
                        for r in state["transactions"]
                        if r["included"]
                        and not r["needs_review"]
                        and r["category"] == "income"
                    )
                    record["passed"] &= record[
                        "no_unresolved_credit_in_headline_income"
                    ]
                    transactions[case["id"]] = sorted(
                        (
                            r["date"],
                            r["description"],
                            r["amount_minor"],
                            r["currency"],
                        )
                        for r in state["transactions"]
                    )
            record["financial_reconciliation"] = (
                sum(c["net_minor"] for c in summary["categories"])
                == summary["net_movement_minor"]
                == summary["cash_in_minor"] - summary["cash_out_minor"]
            )
            record["passed"] &= record["financial_reconciliation"]
        results.append(record)
    for name in ("bank", "card"):
        left, right = f"utilly-{name}.pdf", f"utilly-{name}.csv"
        results.append(
            {
                "id": f"{name}-pdf-csv-every-row-equivalent",
                "passed": left in transactions
                and right in transactions
                and transactions[left] == transactions[right],
            }
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline-ref")
    parser.add_argument("--backend-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    folder = args.download_dir.resolve()
    download_sources(folder, args.offline)
    if args.backend_path:
        sys.path.insert(0, str(args.backend_path))
    results = run_cases(folder)
    if args.worker:
        print(json.dumps(results))
        return
    report = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "scope": "Publicly published demonstration statements and independent fictional samples; no private customer statements. Financial extraction checks, not broad categorization accuracy.",
        "source_documents": len(SOURCES),
        "checks": len(results),
        "passed": sum(row["passed"] for row in results),
        "results": results,
    }
    if args.baseline_ref:
        with tempfile.TemporaryDirectory(prefix="folio-baseline-code-") as directory:
            backend = Path(directory) / "backend"
            (backend / "app").mkdir(parents=True)
            for filename in (
                "__init__.py",
                "engine.py",
                "main.py",
                "parser.py",
                "storage.py",
            ):
                content = subprocess.check_output(
                    ["git", "show", f"{args.baseline_ref}:backend/app/{filename}"],
                    cwd=ROOT,
                )
                (backend / "app" / filename).write_bytes(content)
            baseline = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--download-dir",
                    str(folder),
                    "--offline",
                    "--worker",
                    "--backend-path",
                    str(backend),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            report["baseline"] = {
                "commit": args.baseline_ref,
                "results": json.loads(baseline.stdout),
            }
            report["baseline"]["passed"] = sum(
                row["passed"] for row in report["baseline"]["results"]
            )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "sources": len(SOURCES),
                "checks": len(results),
                "passed": report["passed"],
                "baseline_passed": report.get("baseline", {}).get("passed"),
            },
            indent=2,
        )
    )
    if report["passed"] != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
