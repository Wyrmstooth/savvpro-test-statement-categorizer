"""Export only numeric usage counters and timestamps from a local Codex JSONL log.

Never exports prompts, messages, tool calls, session identifiers, paths or credentials.
The source log stays on the local machine and must never be committed.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

COUNTERS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def extract_usage(source: Path) -> dict:
    events = []
    model = None
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # The active log may end with an incomplete write.
            payload = entry.get("payload", {})
            if entry.get("type") == "turn_context" and isinstance(
                payload.get("model"), str
            ):
                model = payload["model"]
            if entry.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            info = payload.get("info") or {}
            total = info.get("total_token_usage") or {}
            last = info.get("last_token_usage") or {}
            if not all(isinstance(total.get(key), int) for key in COUNTERS):
                continue
            events.append(
                {
                    "timestamp": entry.get("timestamp"),
                    "total_token_usage": {key: total[key] for key in COUNTERS},
                    "last_token_usage": {key: last.get(key, 0) for key in COUNTERS},
                }
            )
    if not events:
        raise ValueError(
            "No valid token-count events found. Do not invent usage figures."
        )
    first, final = events[0], events[-1]
    baseline = {
        key: first["total_token_usage"][key] - first["last_token_usage"][key]
        for key in COUNTERS
    }
    delta = {key: final["total_token_usage"][key] - baseline[key] for key in COUNTERS}
    return {
        "source": "Codex local session token_count events (allowlisted metadata only)",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "model_reported_by_client": model,
        "scope": "Snapshot through the final event below; later documentation, commits and submission are not included.",
        "counter_notes": "Input includes cached input. Reasoning is a subset of output, not an additional billable total.",
        "baseline_before_first_recorded_call": baseline,
        "usage_during_recorded_calls": delta,
        "events": events,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source", type=Path, help="Local Codex JSONL file (never committed)"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("docs/ai-usage/token-log.json")
    )
    args = parser.parse_args()
    result = extract_usage(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "event_count": len(result["events"]),
                **result["usage_during_recorded_calls"],
            }
        )
    )


if __name__ == "__main__":
    main()
