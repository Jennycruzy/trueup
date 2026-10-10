"""Proposed scenarios: data from the planner, checked by code before they are kept.

A proposal is a scenario as JSON (the same fields as Scenario.to_dict). It can
only combine app code and fake behaviours that already exist: the planner never
writes code. `validate` checks the schema and that the app and fake model exist
and fit together; `untraced_check` then runs the app against the fake with no
tracing library (in a subprocess) and rejects the proposal if the truth it
names is not what really happens.

Accepted proposals live in scenarios/proposed/<library>/<id>.json.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from trueup.scenarios.library import ALL, BUILT, Scenario

ROOT = Path(__file__).resolve().parents[3]
FIELDS = ("id", "provider", "api", "framework", "does", "app", "model", "expected")
ID_RE = re.compile(r"^p-[a-z0-9]+(-[a-z0-9]+)*$")
EXPECTED_KEYS = ("calls", "outcome", "exception", "tokens", "finish", "tool_calls", "fake", "tool_runs",
                 "include_usage")
REQUIRED_EXPECTED = ("calls", "outcome", "fake")
PER_CALL = ("tokens", "finish", "tool_calls", "fake", "include_usage")
FAKE_OUTCOMES = ("complete", "failed", "incomplete", "error_event", "cut", "http_error")
ROUTES = {("openai", "chat"): "/v1/chat/completions", ("openai", "responses"): "/v1/responses",
          ("anthropic", "messages"): "/v1/messages"}


def proposed_dir() -> Path:
    return Path(os.environ.get("TRUEUP_PROPOSED_DIR") or ROOT / "scenarios" / "proposed")


def fake_models() -> dict[tuple[str, str], tuple[str, ...]]:
    """Fake behaviours per (provider, api): the model names the fake answers on that route."""
    from trueup.fake import anthropic_messages, openai_chat, openai_responses

    return {
        ("openai", "chat"): openai_chat.SCENARIOS + openai_chat.AGENT_SCENARIOS,
        ("openai", "responses"): openai_responses.SCENARIOS + openai_responses.AGENT_SCENARIOS,
        ("anthropic", "messages"): anthropic_messages.SCENARIOS,
    }


def app_shapes() -> dict[str, tuple[str, str, str]]:
    """Each app -> (provider, api, framework), from the scenarios that already use it."""
    out: dict[str, tuple[str, str, str]] = {}
    for s in ALL:
        out.setdefault(s.app, (s.provider, s.api, s.framework))
    return out


def catalogue() -> dict[str, Any]:
    """What a proposal may use, for the planner prompt."""
    shapes = app_shapes()
    does = {}
    for s in ALL:
        does.setdefault(s.app, s.does)
    return {
        "apps": {a: {"provider": p, "api": api, "framework": fw, "e.g.": does[a]}
                 for a, (p, api, fw) in sorted(shapes.items())},
        "fake_models": {f"{p}/{api}": list(m) for (p, api), m in fake_models().items()},
        "expected_keys": list(EXPECTED_KEYS),
        "required_expected": list(REQUIRED_EXPECTED),
        "fake_outcomes": list(FAKE_OUTCOMES),
    }


def from_dict(d: dict[str, Any]) -> Scenario:
    return Scenario(**{k: d[k] for k in FIELDS}, status=BUILT)


def load(library: str | None = None) -> list[Scenario]:
    base = proposed_dir()
    dirs = [base / library] if library else sorted(p for p in base.glob("*") if p.is_dir())
    return [from_dict(json.loads(f.read_text())) for d in dirs for f in sorted(d.glob("*.json"))]


def find(scenario_id: str) -> Scenario | None:
    for f in proposed_dir().glob(f"*/{scenario_id}.json"):
        return from_dict(json.loads(f.read_text()))
    return None


def _list_of(v: Any, n: int, ok: Any) -> bool:
    return isinstance(v, list) and len(v) == n and all(ok(x) for x in v)


def _tokens_ok(t: Any) -> bool:
    return t is None or (isinstance(t, dict) and set(t) == {"input", "output"}
                         and all(isinstance(x, int) and x >= 0 for x in t.values()))


def validate(p: Any, taken: set[tuple[str, str]] | None = None, ids: set[str] | None = None) -> list[str]:
    """Reasons the proposal is invalid; empty if it passes the schema and fake checks.

    taken: (app, model) pairs already covered; ids: ids already used.
    """
    if not isinstance(p, dict):
        return ["a proposal must be a JSON object"]
    errs = []
    missing = [k for k in FIELDS if k not in p]
    extra = [k for k in p if k not in FIELDS and k != "rationale"]
    if missing:
        errs.append(f"missing fields: {', '.join(missing)}")
    if extra:
        errs.append(f"unknown fields: {', '.join(extra)}")
    if missing:
        return errs
    if not all(isinstance(p[k], str) for k in FIELDS if k != "expected"):
        return [*errs, "id, provider, api, framework, does, app and model must be strings"]
    if not ID_RE.match(p["id"]):
        errs.append(f"id {p['id']!r} must look like p-word-word (lowercase, starts with p-)")
    if p["id"] in {s.id for s in ALL} | (ids or set()):
        errs.append(f"id {p['id']!r} is already used")
    shape = app_shapes().get(p["app"])
    if shape is None:
        errs.append(f"unknown app {p['app']!r}; use one of the listed apps")
    elif (p["provider"], p["api"], p["framework"]) != shape:
        errs.append(f"app {p['app']} is provider={shape[0]} api={shape[1]} framework={shape[2]}, "
                    f"not {p['provider']}/{p['api']}/{p['framework']}")
    else:
        models = fake_models()[(shape[0], shape[1])]
        if p["model"] not in models:
            errs.append(f"fake model {p['model']!r} is not supported on {ROUTES[(shape[0], shape[1])]}; "
                        f"supported: {', '.join(models)}")
    pair = (p["app"], p["model"])
    if pair in {(s.app, s.model) for s in ALL} | (taken or set()):
        errs.append(f"app {p['app']} with fake model {p['model']} is already a scenario; propose something new")
    if not p["does"].strip():
        errs.append("does must say what the app does")
    errs += _validate_expected(p["expected"])
    return errs


def _validate_expected(e: Any) -> list[str]:
    if not isinstance(e, dict):
        return ["expected must be an object"]
    errs = []
    unknown = [k for k in e if k not in EXPECTED_KEYS]
    if unknown:
        errs.append(f"expected has fields the comparer cannot check: {', '.join(unknown)}")
    missing = [k for k in REQUIRED_EXPECTED if k not in e]
    if missing:
        return [*errs, f"expected must name {', '.join(missing)}"]
    n = e["calls"]
    if not isinstance(n, int) or n < 0:
        return [*errs, "expected.calls must be a whole number"]
    if e["outcome"] not in ("ok", "exception"):
        errs.append("expected.outcome must be ok or exception")
    if (e["outcome"] == "exception") != ("exception" in e):
        errs.append("expected.exception (a class name) is required exactly when outcome is exception")
    if "exception" in e and not isinstance(e["exception"], str):
        errs.append("expected.exception must be a class name")
    checks = {
        "fake": lambda x: x in FAKE_OUTCOMES,
        "tokens": _tokens_ok,
        "finish": lambda x: isinstance(x, list) and all(isinstance(y, str) for y in x),
        "tool_calls": lambda x: isinstance(x, list) and all(isinstance(y, str) for y in x),
        "include_usage": lambda x: isinstance(x, bool),
    }
    for k in PER_CALL:
        if k in e and not _list_of(e[k], n, checks[k]):
            errs.append(f"expected.{k} must be a list with one valid entry per call ({n})")
    if "tool_runs" in e and not (isinstance(e["tool_runs"], list) and all(
            isinstance(t, dict) and set(t) == {"name", "outcome"} and t["outcome"] in ("ok", "raised")
            for t in e["tool_runs"])):
        errs.append('expected.tool_runs must be a list of {"name", "outcome": "ok" | "raised"}')
    return errs


def untraced_check(p: dict[str, Any], timeout: float = 120) -> tuple[list[str], dict[str, Any] | None]:
    """Run the proposal's app against the fake with no tracing library, in a subprocess.

    Returns (differences between expected and real truth, real truth). The child gets
    the same env as scenario runs: no real keys, export off.
    """
    from trueup.runner.run import child_env

    try:
        r = subprocess.run([sys.executable, "-m", "trueup.scenarios.untraced", json.dumps(p)], env=child_env(),
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return [f"the untraced run timed out after {timeout:.0f} s"], None
    if r.returncode != 0 or not r.stdout.strip():
        tail = (r.stderr or "").strip().splitlines()[-1:] or ["no output"]
        return [f"the untraced run failed: {tail[0][:300]}"], None
    t = json.loads(r.stdout.strip().splitlines()[-1])
    diffs = [f"expected.{k} is {json.dumps(v)} but the untraced run gives {json.dumps(t.get(k))}"
             for k, v in p["expected"].items() if t.get(k) != v]
    return diffs, t


def save(p: dict[str, Any], library: str) -> Path:
    d = proposed_dir() / library
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{p['id']}.json"
    path.write_text(json.dumps({k: p[k] for k in FIELDS}, indent=1) + "\n")
    return path
