"""The checker: false-alarm control for leads. Pure: every rule reads recorded evidence.

A lead becomes a finding only if every rule passes. The effects that gather the
evidence (reruns, the main-branch venv, the repro run) live in trueup.check.

Evidence for one lead (a dict; keys a rule does not need may be missing):
  lead         {scenario, library, check, field, truth, trace, severity}
  observation  the sweep's observation for the scenario (truth and trace)
  reruns       two fresh-process reruns on the latest release:
               [{status, reason, leads: [signature], versions, seconds, framework}]
  latest       {installed: {dist: version}, pypi: {dist: version or None}}
  main         {status: ran | not_run | could_not_install, reason, leads, commit}
  harness      {env: {name: value}} for the export-related variables the child got
  others       {library: {status, leads: [signature]}} for the same scenario
  repro        {status, reason, lines, exit, leads: [signature], path}

A signature is [check, field, truth, trace], so "same result" means the same
disagreement with the same values.

Rule results: pass, fail, could_not_check (with a reason) or disputed (rule 6 only).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PASS, FAIL, COULD_NOT_CHECK, DISPUTED = "pass", "fail", "could_not_check", "disputed"
FINDING, WITHDRAWN, LEAD, DISPUTED_SEMANTICS = "finding", "withdrawn", "lead", "disputed semantics"
REPRO_MAX_LINES = 40
# A neatlogs exporter retrying a dead endpoint takes ~200 s; a healthy run takes a few seconds.
SLOW_RUN_S = 60.0
LOOP_ERRORS = ("Event loop is closed", "attached to a different loop", "different event loop")

RULES = ("fresh_process", "recommended_setup", "latest_and_main", "fake_truthful", "harness_sane", "reference",
         "repro")

# Framework distributions that must be installed for a framework scenario to mean anything.
FRAMEWORK_DISTS = {
    "langchain": ("langchain-core", "langchain-openai"),
    "langgraph": ("langchain-core", "langchain-openai", "langgraph"),
    "openai-agents": ("openai-agents",),
}

# Where the OpenTelemetry specs (GenAI semantic conventions, trace API) define the right
# behaviour, per check. Only what the spec states; anything else needs a second library.
SEMCONV = {
    "run_status": "OTel trace API: set span status to Error when the operation it covers failed",
    "call_status": "OTel GenAI spans: status Error and error.type when the model call ends in an error",
    "span_closed": "OTel trace API: every started span must be ended (Span.End) to be exported",
    "tokens": "OTel GenAI: gen_ai.usage.input_tokens and gen_ai.usage.output_tokens on the inference span",
    "finish": "OTel GenAI: gen_ai.response.finish_reasons on the inference span",
    "output_text": "OTel GenAI: text parts in gen_ai.output.messages (when content capture is on)",
    "output_tools": "OTel GenAI: tool_call parts with name and arguments in gen_ai.output.messages",
    "error_recorded": "OTel trace API: set span status to Error when the operation it covers failed",
}


@dataclass(frozen=True)
class RuleResult:
    rule: str
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "status": self.status, "reason": self.reason}


def signature(m: dict[str, Any]) -> list[Any]:
    """[check, field, truth, trace] with values normalised through JSON."""
    norm = lambda v: json.loads(json.dumps(v, default=str, sort_keys=True))  # noqa: E731
    return [m["check"], m["field"], norm(m["truth"]), norm(m["trace"])]


def _same_place(lead: dict[str, Any], sigs: list[list[Any]]) -> bool:
    return any(s[0] == lead["check"] and s[1] == lead["field"] for s in sigs)


def _r(rule: str, status: str, reason: str) -> RuleResult:
    return RuleResult(rule, status, reason)


def fresh_process(ev: dict[str, Any]) -> RuleResult:
    """1. Reproduces in a fresh process, twice, with the same result."""
    rule, sig = "fresh_process", signature(ev["lead"])
    reruns = ev.get("reruns") or []
    if len(reruns) < 2:
        return _r(rule, COULD_NOT_CHECK, f"{len(reruns)} of 2 reruns recorded")
    for i, r in enumerate(reruns[:2], 1):
        if r.get("status") != "ran":
            return _r(rule, COULD_NOT_CHECK, f"rerun {i} did not run: {r.get('reason')}")
        if sig not in r.get("leads", []):
            other = [s for s in r.get("leads", []) if s[:2] == sig[:2]]
            got = f"got {other[0][3]!r} instead" if other else "lead absent"
            return _r(rule, FAIL, f"rerun {i}: {got}")
    return _r(rule, PASS, "same lead with the same values in 2 fresh processes")


def recommended_setup(ev: dict[str, Any]) -> RuleResult:
    """2. Reproduces on the library's recommended setup with the framework package installed."""
    rule = "recommended_setup"
    reruns = [r for r in ev.get("reruns") or [] if r.get("status") == "ran"]
    if not reruns:
        return _r(rule, COULD_NOT_CHECK, "no rerun ran")
    r = reruns[0]
    framework = r.get("framework", "none")
    versions = r.get("versions") or {}
    missing = [d for d in FRAMEWORK_DISTS.get(framework, ()) if not versions.get(d)]
    if missing:
        return _r(rule, FAIL, f"{framework} scenario ran without {', '.join(missing)} installed")
    setup = r.get("setup") or "recommended setup"
    return _r(rule, PASS, f"{setup}; framework {framework}" + (" (packages installed)" if framework != "none" else ""))


def latest_and_main(ev: dict[str, Any]) -> RuleResult:
    """3. Reproduces on the latest release and on the library's main branch."""
    rule, lead = "latest_and_main", ev["lead"]
    latest = ev.get("latest") or {}
    installed, pypi = latest.get("installed") or {}, latest.get("pypi") or {}
    if not installed:
        return _r(rule, COULD_NOT_CHECK, "installed versions not recorded")
    behind = [f"{d} {v} < {pypi[d]}" for d, v in installed.items() if pypi.get(d) and v != pypi[d]]
    if behind:
        return _r(rule, FAIL, "not the latest release: " + "; ".join(behind))
    unknown = [d for d in installed if not pypi.get(d)]
    main = ev.get("main") or {}
    if main.get("status") != "ran":
        return _r(rule, COULD_NOT_CHECK, f"main branch: {main.get('reason') or 'not run'}")
    if not _same_place(lead, main.get("leads", [])):
        return _r(rule, FAIL, f"does not reproduce on main ({main.get('commit', '?')[:10]}); fixed there")
    note = f"; PyPI latest unknown for {', '.join(unknown)}" if unknown else ""
    return _r(rule, PASS, f"latest release and main {main.get('commit', '?')[:10]}{note}")


def fake_truthful(ev: dict[str, Any]) -> RuleResult:
    """4. The fake sent what truth claims: usage present when tokens are compared; unique ids per call."""
    rule, lead = "fake_truthful", ev["lead"]
    truth = (ev.get("observation") or {}).get("truth") or {}
    calls = truth.get("fake_log") or []
    ids = [c.get("response_id") for c in calls if c.get("response_id")]
    if len(ids) != len(set(ids)):
        return _r(rule, FAIL, "the fake reused a response id across calls")
    if truth.get("expected_mismatch"):
        return _r(rule, FAIL, f"truth differs from the scenario's expectation: {truth['expected_mismatch']}")
    if lead["check"] == "tokens":
        n = _call_index(lead["field"])
        call = calls[n] if n is not None and n < len(calls) else None
        if call is None:
            return _r(rule, FAIL, f"{lead['field']}: no such call in the fake's log")
        if not call.get("usage_sent") or not call.get("usage"):
            return _r(rule, FAIL, f"{lead['field']}: the fake sent no usage, so there is nothing to compare")
    return _r(rule, PASS, f"{len(calls)} call(s), unique response ids" +
              ("; usage was sent" if lead["check"] == "tokens" else ""))


def _call_index(field: str) -> int | None:
    parts = field.split()
    if len(parts) >= 2 and parts[0] == "call" and parts[1].isdigit():
        return int(parts[1]) - 1
    return None


def harness_sane(ev: dict[str, Any]) -> RuleResult:
    """5. No shared async client across event loops; no export to a dead endpoint."""
    rule = "harness_sane"
    app = ((ev.get("observation") or {}).get("truth") or {}).get("app") or {}
    msg = app.get("message") or ""
    if any(e in msg for e in LOOP_ERRORS):
        return _r(rule, FAIL, f"app error is an event-loop error from the harness: {msg[:80]}")
    env = (ev.get("harness") or {}).get("env") or {}
    endpoints = [k for k in ("NEATLOGS_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                             "TRACELOOP_BASE_URL") if env.get(k)]
    if endpoints:
        return _r(rule, FAIL, f"the child had an export endpoint set: {', '.join(endpoints)}")
    if env.get("NEATLOGS_DISABLE_EXPORT") != "true" or env.get("OTEL_TRACES_EXPORTER") != "none":
        return _r(rule, FAIL, "export was not turned off in the child")
    slow = [r["seconds"] for r in ev.get("reruns") or [] if (r.get("seconds") or 0) > SLOW_RUN_S]
    if slow:
        return _r(rule, FAIL, f"a rerun took {slow[0]:.0f} s, which looks like export retries")
    return _r(rule, PASS, "own client per event loop; export off, no endpoint; reruns fast")


def reference(ev: dict[str, Any]) -> RuleResult:
    """6. Another library shows the right behaviour, or the OTel conventions define it."""
    rule, lead = "reference", ev["lead"]
    others = ev.get("others") or {}
    right = [lib for lib, o in sorted(others.items()) if o.get("status") == "ran" and not _same_place(lead, o["leads"])]
    if right:
        return _r(rule, PASS, f"{', '.join(right)} record(s) it correctly on the same scenario")
    ref = semconv_reference(lead, ((ev.get("observation") or {}).get("truth") or {}).get("fake_log") or [])
    if ref:
        return _r(rule, PASS, ref)
    ran = [lib for lib, o in others.items() if o.get("status") == "ran"]
    if not ran:
        return _r(rule, COULD_NOT_CHECK, "no other library ran this scenario and no OTel reference")
    return _r(rule, DISPUTED, f"{', '.join(sorted(ran))} behave the same and no OTel convention defines it")


def semconv_reference(lead: dict[str, Any], calls: list[dict[str, Any]] = ()) -> str | None:
    check, field, trace = lead["check"], lead["field"], lead["trace"]
    n = _call_index(field)
    call = calls[n] if n is not None and n < len(calls) else {}
    if check == "call_status" and isinstance(trace, str) and trace.startswith("ERROR"):
        return None  # status is right; the conventions do not require the exception event
    if check == "output":
        if field.endswith("tool calls"):
            return SEMCONV["output_tools"]
        if "refusal" in (call.get("scenario") or ""):
            return None  # the GenAI conventions have no refusal part
        return SEMCONV["output_text"]
    return SEMCONV.get(check)


def repro(ev: dict[str, Any]) -> RuleResult:
    """7. A minimal repro under 40 lines that runs with no keys exists and reproduces."""
    rule, r = "repro", ev.get("repro") or {}
    if r.get("status") != "ran":
        return _r(rule, COULD_NOT_CHECK, f"repro did not run: {r.get('reason') or 'not generated'}")
    if r.get("lines", REPRO_MAX_LINES) >= REPRO_MAX_LINES:
        return _r(rule, FAIL, f"repro is {r.get('lines')} lines (limit {REPRO_MAX_LINES})")
    if signature(ev["lead"]) not in r.get("leads", []):
        return _r(rule, FAIL, "the repro ran but did not show the lead")
    return _r(rule, PASS, f"{r.get('path')}: {r['lines']} lines, no keys, shows the lead")


CHECKS = (fresh_process, recommended_setup, latest_and_main, fake_truthful, harness_sane, reference, repro)


def run_rules(ev: dict[str, Any]) -> list[RuleResult]:
    return [f(ev) for f in CHECKS]


def verdict(results: list[RuleResult]) -> tuple[str, RuleResult | None]:
    """(status, the rule that decided it). Status is finding, withdrawn, lead or disputed semantics."""
    for r in results:
        if r.status == FAIL:
            return WITHDRAWN, r
    open_ = [r for r in results if r.status == COULD_NOT_CHECK and r.rule != "latest_and_main"]
    if open_:
        return LEAD, open_[0]
    disputed = [r for r in results if r.status == DISPUTED]
    if disputed:
        return DISPUTED_SEMANTICS, disputed[0]
    main = next((r for r in results if r.rule == "latest_and_main"), None)
    if main is not None and main.status == COULD_NOT_CHECK:
        # Every other rule passed: a finding if the reason main could not be checked is recorded.
        return (FINDING, main) if main.reason else (LEAD, main)
    return FINDING, None
