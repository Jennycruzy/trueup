"""Turn the fake's log and the app outcome into truth fields. Pure functions."""

from __future__ import annotations

from typing import Any


def derive(fake_log: list[dict[str, Any]], app: dict[str, Any]) -> dict[str, Any]:
    """Truth in the same shape as a scenario's `expected`."""
    out: dict[str, Any] = {
        "calls": len(fake_log),
        "outcome": app["outcome"],
        "tokens": [
            None if e["usage"] is None else {"input": e["usage"]["input_tokens"], "output": e["usage"]["output_tokens"]}
            for e in fake_log
        ],
        "finish": [e["finish"] for e in fake_log],
        "tool_calls": [[t["name"] for t in e["tool_calls"]] for e in fake_log],
        "fake": [e["outcome"] for e in fake_log],
        "response_ids": [e["response_id"] for e in fake_log],
    }
    if app["outcome"] == "exception":
        out["exception"] = app["exception_type"]
    return out


def check_expected(expected: dict[str, Any], truth: dict[str, Any]) -> list[str]:
    """Keys where the run's truth differs from what the scenario expects."""
    return [k for k, v in expected.items() if truth.get(k) != v]
