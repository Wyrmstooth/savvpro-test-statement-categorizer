import importlib.util
import json
from pathlib import Path


def test_usage_export_excludes_conversation_and_credentials(tmp_path):
    source = Path(__file__).resolve().parents[2] / "scripts" / "export_ai_usage.py"
    spec = importlib.util.spec_from_file_location("usage_export", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    counters = dict(
        input_tokens=100,
        cached_input_tokens=50,
        output_tokens=30,
        reasoning_output_tokens=10,
        total_tokens=130,
    )
    entries = [
        {"type": "turn_context", "payload": {"model": "example-model", "private": "DO_NOT_EXPORT"}},
        {
            "type": "event_msg",
            "timestamp": "2026-10-26T00:00:00Z",
            "payload": {
                "type": "token_count",
                "credentials": "DO_NOT_EXPORT",
                "info": {
                    "total_token_usage": {**counters, "secret": "DO_NOT_EXPORT"},
                    "last_token_usage": counters,
                },
            },
        },
        {"type": "response_item", "payload": {"content": "DO_NOT_EXPORT"}},
    ]
    log = tmp_path / "synthetic.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in entries) + "\n{incomplete", encoding="utf-8")
    result = module.extract_usage(log)
    assert "DO_NOT_EXPORT" not in json.dumps(result)
    assert result["usage_during_recorded_calls"] == counters
    assert result["model_reported_by_client"] == "example-model"
