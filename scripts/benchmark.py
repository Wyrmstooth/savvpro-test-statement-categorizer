"""Measure a fictional 10,000-row import through the real API into disposable SQLite."""

import argparse
import csv
import io
import json
import platform
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from app.main import create_app
from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rows", type=int, default=10000, choices=range(1, 10001), metavar="1..10000"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    merchants = [
        "ADOBE CREATIVE CLOUD",
        "UBER TRIP",
        "AMAZON MKTPLACE",
        "GOOGLE ADS",
        "TRANSFER TO SAVINGS",
        "JOES CAFE",
        "NOTION LABS",
        "UNKNOWN MERCHANT",
    ]
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["Date", "Description", "Amount"])
    for index in range(args.rows):
        writer.writerow(
            [
                f"2026-10-{index % 28 + 1:02d}",
                f"{merchants[index % len(merchants)]} REF {index}",
                f"-{index % 500 + 1}.37",
            ]
        )
    data = stream.getvalue().encode()
    with (
        tempfile.TemporaryDirectory(prefix="folio-benchmark-") as directory,
        TestClient(create_app(str(Path(directory) / "benchmark.db"))) as client,
    ):
        start = perf_counter()
        response = client.post(
            "/api/statements", files={"file": ("fictional-benchmark.csv", data)}
        )
        imported_seconds = perf_counter() - start
        response.raise_for_status()
        start = perf_counter()
        state = client.get("/api/workspace").json()
        read_seconds = perf_counter() - start
        assert state["summary"]["total"] == args.rows
        assert (
            sum(g["net_minor"] for g in state["summary"]["categories"])
            == state["summary"]["net_movement_minor"]
        )
    result = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "rows": args.rows,
        "file_bytes": len(data),
        "import_seconds": round(imported_seconds, 4),
        "workspace_read_seconds": round(read_seconds, 4),
        "review_count": state["summary"]["review_count"],
        "scope": "Synthetic local API/SQLite throughput measurement, not a real-statement accuracy benchmark or SLA.",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
