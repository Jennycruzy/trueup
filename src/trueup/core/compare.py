"""Compare truth (the fake's log and the app outcome) with the exported spans. Pure.

Checks, in order:
  run_status   app raised / got a result -> top-level span ERROR / not ERROR. The top level is
               the trace root (for the Agents SDK, "Agent workflow"); orphans only if no root
               was exported
  call_status  provider error or failed stream -> that LLM span ERROR with an exception event
  call_count   one LLM span per provider request (this check reports extra spans)
  span_closed  every request has an ended, exported span (this check reports missing spans)
  tokens       per-span input/output tokens equal what the provider sent; only where usage was sent
  output       text, refusal and tool calls the app received are on the span; tool args equal as JSON
  finish       finish reason / response status recorded; failed and incomplete visible
  tools        framework runs: every tool that really ran has a tool span; a tool that raised
               has an ERROR span or an exception event
  error_recorded  the app raised and no provider call failed (the error came from the
               framework: unknown tool, max turns, a tool) -> some span is ERROR or has an
               exception event
  request_changed  (note) the library changed the request, e.g. added stream_options.include_usage

Severity: HIGH changes a number or status a dashboard shows by default (run
status, cost, call count); MEDIUM is wrong or missing detail in a span; LOW is
extra or cosmetic.
"""

from __future__ import annotations

import json
from typing import Any

from trueup.core.adapters import ADAPTERS, Adapter, SpanFacts, facts, is_llm_span, norm_finish, tool_span_name
from trueup.core.model import Mismatch, Observation, Severity

HIGH, MEDIUM, LOW = Severity.HIGH, Severity.MEDIUM, Severity.LOW
CHECKS = ("run_status", "call_status", "call_count", "span_closed", "tokens", "output", "finish", "tools",
          "error_recorded", "request_changed")

FAILED_CALL = ("http_error", "error_event", "cut")
# The app got the whole reply for these, so output and finish must be on the span.
COMPLETE_CALL = ("complete", "incomplete")


def _lead(check: str, field: str, truth: Any, trace: Any, severity: Severity) -> Mismatch:
    return Mismatch(field=field, truth=truth, trace=trace, severity=severity, check=check)


def top_level(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trace roots. A span whose parent was not exported counts only when no root was."""
    roots = [s for s in spans if s.get("parent_id") is None]
    if roots:
        return roots
    ids = {s["span_id"] for s in spans}
    return [s for s in spans if s.get("parent_id") not in ids]


def _errored(span: dict[str, Any]) -> bool:
    return span["status"]["code"] == "ERROR" or any(e.get("name") == "exception" for e in span.get("events", []))


def match_calls(calls: list[dict[str, Any]], llm: list[tuple[dict[str, Any], SpanFacts]]) -> list[int | None]:
    """For each call, the index of its LLM span (or None). Response id first, then start order."""
    out: list[int | None] = [None] * len(calls)
    used: set[int] = set()
    for ci, c in enumerate(calls):
        for si, (_, f) in enumerate(llm):
            if si not in used and c.get("response_id") and f.response_id == c["response_id"]:
                out[ci] = si
                used.add(si)
                break
    free = [si for si in range(len(llm)) if si not in used and llm[si][1].response_id is None]
    for ci in range(len(calls)):
        if out[ci] is None and free:
            out[ci] = free.pop(0)
    return out


def _args_equal(truth: Any, trace: Any) -> bool:
    def parse(v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return v
        return v

    return parse(truth) == parse(trace)


def _partial_read(truth: dict[str, Any]) -> bool:
    # The app closed the stream early, so it never received the full reply.
    result = (truth.get("app") or {}).get("result")
    return isinstance(result, dict) and "chunks_read" in result


def compare(obs: Observation, adapter: Adapter | None = None) -> list[Mismatch]:
    truth, trace = obs.truth, obs.trace
    adapter = adapter or ADAPTERS[trace["library"]]
    calls: list[dict[str, Any]] = list(truth.get("fake_log") or [])
    spans: list[dict[str, Any]] = sorted(trace.get("spans") or [], key=lambda s: s.get("start_ns") or 0)
    llm = [(s, facts(adapter, s)) for s in spans if is_llm_span(adapter, s)]
    app_raised = truth.get("outcome") == "exception"
    out: list[Mismatch] = []

    # run_status
    tops = top_level(spans)
    if tops:
        codes = [s["status"]["code"] for s in tops]
        if app_raised and "ERROR" not in codes:
            out.append(_lead("run_status", "top-level span status", f"ERROR (app raised {truth.get('exception')})",
                             "/".join(codes), HIGH))
        failed_reply = any(c.get("outcome") == "failed" for c in calls)
        if not app_raised and "ERROR" in codes and not failed_reply:
            out.append(_lead("run_status", "top-level span status", "not ERROR (app got a result)", "ERROR", HIGH))

    match = match_calls(calls, llm)

    # call_count: extra LLM spans (duplicates). Missing ones are span_closed.
    if len(llm) > len(calls):
        out.append(_lead("call_count", "LLM spans", f"{len(calls)} (provider requests)", len(llm), HIGH))

    tokens_sum_ok = True
    if len(llm) == len(calls) and any(c.get("usage_sent") for c in calls):
        real = sum(c["usage"]["input_tokens"] + c["usage"]["output_tokens"] for c in calls if c.get("usage_sent"))
        seen = sum((f.input_tokens or 0) + (f.output_tokens or 0) for _, f in llm)
        tokens_sum_ok = real == seen

    expected = truth.get("expected") or {}
    expected_tokens = expected.get("tokens")
    partial = _partial_read(truth)

    for ci, call in enumerate(calls):
        where = f"call {ci + 1}"
        outcome = call.get("outcome")
        si = match[ci]

        # request_changed (note): the app did not ask for usage, the request carried include_usage.
        # The scenario says what the app asks for; without that, no expected usage means it did not ask.
        if "include_usage" in expected:
            app_asked = ci < len(expected["include_usage"]) and expected["include_usage"][ci]
        else:
            app_asked = not (isinstance(expected_tokens, list) and ci < len(expected_tokens)
                             and expected_tokens[ci] is None)
        if not app_asked and call.get("include_usage"):
            out.append(Mismatch(field=f"{where} stream_options.include_usage", truth="not set by the app",
                                trace="set in the request the provider got", severity=LOW,
                                check="request_changed", kind="note"))

        if si is None:
            out.append(_lead("span_closed", f"{where} span", f"ended and exported ({outcome})", "no span", HIGH))
            continue
        span, f = llm[si]

        if outcome in FAILED_CALL:
            has_exc = any(e.get("name") == "exception" for e in span.get("events", []))
            if span["status"]["code"] != "ERROR" or not has_exc:
                actual = span["status"]["code"] + ("" if has_exc else ", no exception event")
                out.append(_lead("call_status", f"{where} span status", f"ERROR with exception event ({outcome})",
                                 actual, MEDIUM))

        if call.get("usage_sent") and not partial:
            want = {"input": call["usage"]["input_tokens"], "output": call["usage"]["output_tokens"]}
            got = {"input": f.input_tokens, "output": f.output_tokens}
            if want != got:
                out.append(_lead("tokens", f"{where} tokens", want, got, MEDIUM if tokens_sum_ok else HIGH))

        if outcome in COMPLETE_CALL and not partial:
            recorded = set(f.texts) | set(f.refusals)
            for t in call.get("text") or []:
                if t and t not in recorded:
                    out.append(_lead("output", f"{where} output text", t, sorted(recorded) or None, MEDIUM))
            want_tools = call.get("tool_calls") or []
            got_tools = list(f.tool_calls)
            if len(want_tools) != len(got_tools) or not all(
                w["name"] == g[0] and _args_equal(w["arguments"], g[1]) for w, g in zip(want_tools, got_tools)
            ):
                out.append(_lead("output", f"{where} tool calls",
                                 [[w["name"], w["arguments"]] for w in want_tools] or None,
                                 [[g[0], g[1]] for g in got_tools] or None, MEDIUM))

        if outcome in ("complete", "incomplete", "failed") and not partial and call.get("finish"):
            want_f = {norm_finish(x) for x in call["finish"]}
            got_f = {norm_finish(x) for x in f.finish}
            errored = span["status"]["code"] == "ERROR"
            if outcome == "failed":
                ok = errored or "failed" in got_f
            elif outcome == "incomplete":
                ok = errored or "length" in got_f
            elif want_f == {"stop"} and call.get("tool_calls") and "completed" in call["finish"]:
                # A completed Responses call that asks for tools: "tool_call" says the same thing.
                ok = got_f in ({"stop"}, {"tool_call"})
            else:
                ok = want_f == got_f
            if not ok:
                out.append(_lead("finish", f"{where} finish", sorted(call["finish"]),
                                 sorted(f.finish) or None, MEDIUM))

    out += _tools(truth.get("tool_runs") or [], spans, adapter)

    # error_recorded: an error that did not come from a provider call must still show somewhere.
    if app_raised and spans and not any(c.get("outcome") in FAILED_CALL for c in calls):
        if not any(_errored(s) for s in spans):
            out.append(_lead("error_recorded", "any span", f"ERROR or exception event ({truth.get('exception')})",
                             "no span records an error", MEDIUM))
    return out


def _tools(runs: list[dict[str, Any]], spans: list[dict[str, Any]], adapter: Adapter) -> list[Mismatch]:
    """Pair each real tool run with a tool span of the same name, in start order."""
    if adapter.tool_kind is None:
        return []
    by_name: dict[str, list[dict[str, Any]]] = {}
    for s in spans:
        name = tool_span_name(adapter, s)
        if name is not None:
            by_name.setdefault(name, []).append(s)
    out = []
    for i, run in enumerate(runs):
        where = f"tool run {i + 1} ({run['name']})"
        queue = by_name.get(run["name"]) or []
        if not queue:
            out.append(_lead("tools", f"{where} span", f"tool span ({run['outcome']})", "no span", MEDIUM))
            continue
        span = queue.pop(0)
        if run["outcome"] == "raised" and not _errored(span):
            out.append(_lead("tools", f"{where} status", "ERROR or exception event (tool raised)",
                             span["status"]["code"], MEDIUM))
    extra = sum(len(q) for q in by_name.values())
    if extra:
        out.append(_lead("tools", "tool spans", f"{len(runs)} (tool runs)", len(runs) + extra, LOW))
    return out


def leads(mismatches: list[Mismatch]) -> list[Mismatch]:
    return [m for m in mismatches if m.kind == "lead"]
