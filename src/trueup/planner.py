"""trueup plan <library> [--max N]: the model proposes new scenarios as data; code decides.

The planner reads the library's wrapper source from its venv, the scenario
library and the latest findings, and asks the model for new scenarios as JSON.
Every proposal is checked by trueup.scenarios.proposed (schema, app and fake
behaviour exist, truth matches an untraced run). A rejected proposal goes back
to the model with the reason, at most REVISIONS times. Accepted ones are saved
to scenarios/proposed/<library>/ for `trueup sweep <library> --proposed`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from trueup import tracing
from trueup.model import PLAN_MODEL, ModelClient, ModelError, record_spend
from trueup.scenarios import ALL
from trueup.scenarios import proposed as prop
from trueup.state import State

REVISIONS = 2
SOURCE_LIMIT = 60_000  # characters of wrapper source sent to the model
FILE_LIMIT = 32_000

# Wrapper files per library, relative to site-packages, most relevant first.
WRAPPER_FILES = {
    "neatlogs": ["neatlogs/openai.py", "neatlogs/anthropic.py"],
    "openllmetry": ["opentelemetry/instrumentation/openai/shared/chat_wrappers.py",
                    "opentelemetry/instrumentation/anthropic/streaming.py",
                    "opentelemetry/instrumentation/openai/v1/responses_wrappers.py"],
    "openinference": ["openinference/instrumentation/openai/_stream.py",
                      "openinference/instrumentation/openai/_request.py",
                      "openinference/instrumentation/anthropic/_stream.py"],
}

SYSTEM = """You plan test scenarios for Trueup, which checks whether an AI tracing library's spans match \
what really happened. A scenario runs one existing app function against a fake provider; the fake model name \
picks the fake's behaviour. You cannot write code: a scenario is JSON data that combines an existing app with an \
existing fake model, plus the truth you expect the run to produce.

Propose scenarios that are NEW (an app + fake model pair not already in the library) and likely to expose a \
tracing bug, given the wrapper source: code paths the existing scenarios miss (a different app reading style on \
the same failure, streaming vs non-streaming, async, tools with errors, refusal through streaming, ...).

Expected truth fields (only listed ones are checked, against what the fake really did):
  calls: number of requests the fake received
  outcome: "ok" or "exception" (what the app saw); exception: the exception class name when outcome is exception
  fake: per call, what the fake did: complete, failed, incomplete, error_event, cut, http_error
  tokens: per call {"input": n, "output": n}, or null when the fake sent no usage
  finish: per call, list of finish reasons / response status
  tool_calls: per call, list of tool names the model asked for
  tool_runs: framework apps only, [{"name", "outcome": "ok"|"raised"}]
  include_usage: per call, whether the app's request asked for stream usage
Facts about the fake: OpenAI replies use 11 input / 7 output tokens, Anthropic 5 / 3. Streams send usage only \
when the app asks (include_usage) on chat; Responses and Anthropic streams always send it. Leave out a field \
when unsure rather than guess; calls, outcome and fake are required, and exception is required when outcome is \
"exception". Each app's "e.g." is what an existing scenario with it does: keep "does" true to the app (an app \
that does not stream does not stream, whatever the fake model).

Reply with JSON only, no prose: {"proposals": [{"id": "p-...", "provider", "api", "framework", "does", "app", \
"model", "expected": {...}, "rationale": "why a wrapper might get this wrong"}]}"""


def wrapper_source(root: Path, library: str) -> str:
    site = next((root / ".trueup" / "venvs" / library / "lib").glob("python*/site-packages"), None)
    if site is None:
        raise FileNotFoundError(f"no venv for {library}; run `trueup sweep {library}` first")
    parts, total = [], 0
    for rel in WRAPPER_FILES[library]:
        f = site / rel
        if not f.exists() or total >= SOURCE_LIMIT:
            continue
        text = f.read_text()[: min(FILE_LIMIT, SOURCE_LIMIT - total)]
        total += len(text)
        parts.append(f"### {rel}\n{text}")
    return "\n\n".join(parts)


def latest_findings(root: Path, library: str) -> list[dict[str, Any]]:
    runs = sorted((root / ".trueup" / "runs").glob(f"*-{library}/findings.json"))
    if not runs:
        return []
    d = json.loads(runs[-1].read_text())
    out = [{"title": f["title"], "severity": f["severity"], "check": f["details"]["check"],
            "scenarios": f["details"]["scenarios"]} for f in d["findings"]]
    out += [{"title": f.get("title"), "verdict": "disputed"} for f in d.get("disputed_semantics", [])]
    return out


def library_summary() -> list[dict[str, Any]]:
    return [{"id": s.id, "app": s.app, "model": s.model, "framework": s.framework} for s in ALL] + [
        {"id": s.id, "app": s.app, "model": s.model, "framework": s.framework, "proposed": True}
        for s in prop.load()]


VARIANTS = ("v1", "v2")


def seen_outcomes() -> list[dict[str, Any]]:
    """v2: what the fake really did and what the app really saw, for every existing scenario (its truth
    was confirmed by an untraced run). v1's first tries were rejected for guessing these: 3 wrong
    exception classes and 1 wrong fake outcome (sessions 20261010T234842Z-plan-openllmetry, read back
    from neatlogs, and 20261010T235208Z-plan-neatlogs, whose trace never reached neatlogs; plan.json)."""
    rows = []
    for s in [*ALL, *prop.load()]:
        e = s.expected
        if s.status != "built" or "fake" not in e:
            continue
        rows.append({"app": s.app, "model": s.model, "calls": e.get("calls"), "fake": e["fake"],
                     "outcome": e.get("outcome"), **({"exception": e["exception"]} if e.get("exception") else {})})
    return rows


def first_prompt(library: str, source: str, findings: list[dict[str, Any]], n: int,
                 variant: str = "v2") -> list[dict[str, str]]:
    from trueup.managed_prompts import production

    seen = ""
    if variant == "v2":
        seen = ("What really happened in the existing scenarios (untraced runs). The same fake model gives "
                "the same fake outcome and the same exception class on another app of the same provider, api "
                "and streaming style; an app that does not stream gets HTTP 400 (http_error, BadRequestError) "
                f"from a stream-only fake model:\n{json.dumps(seen_outcomes())}\n\n")
    user = (f"Library under test: {library}.\n\nWhat a scenario may use:\n{json.dumps(prop.catalogue())}\n\n"
            f"Existing scenarios (do not repeat an app + model pair):\n{json.dumps(library_summary())}\n\n{seen}"
            f"Current findings for {library}:\n{json.dumps(findings)}\n\n"
            f"Wrapper source of {library} as installed:\n{source}\n\nPropose at most {n} new scenarios.")
    system = production(f"trueup-planner-{variant}", SYSTEM, enabled=tracing.active())
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def revision_prompt(p: Any, reasons: list[str]) -> list[dict[str, str]]:
    user = (f"What a scenario may use:\n{json.dumps(prop.catalogue())}\n\nExisting app + model pairs:\n"
            f"{json.dumps(sorted({f'{s.app}+{s.model}' for s in ALL}))}\n\nYour proposal:\n{json.dumps(p)}\n\n"
            "It was rejected:\n- " + "\n- ".join(reasons) +
            '\n\nFix it and reply with JSON only: {"proposals": [<the one fixed proposal>]}.'
            ' Reply {"proposals": []} to withdraw it.')
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def check(p: Any, taken: set[tuple[str, str]], ids: set[str],
          untraced: Callable[[dict[str, Any]], tuple[list[str], Any]]) -> list[str]:
    reasons = prop.validate(p, taken, ids)
    if reasons:
        return reasons
    diffs, truth = untraced(p)
    if not diffs and truth and p["api"] == "chat" and "include_usage" not in p["expected"]:
        # The untraced run has no library, so its request shows what the app itself asks for.
        # Without this the comparer guesses from tokens and can report a library change that is not one.
        p["expected"]["include_usage"] = truth["include_usage"]
    return diffs


def plan(root: Path, library: str, max_n: int = 5, *, client: ModelClient | None = None,
         run_id: str | None = None, out: Callable[[str], None] = print,
         untraced: Callable[[dict[str, Any]], tuple[list[str], Any]] = prop.untraced_check,
         save: bool = True, variant: str = "v2", save_dir: Path | None = None) -> dict[str, Any]:
    from trueup.sweep import new_run_id

    run_id = run_id or new_run_id(f"plan-{library}")
    run_dir = root / ".trueup" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with State(root) as state:
        state.begin_run(run_id, "plan", library)
    client = client or ModelClient()
    record_spend(run_dir, "before", client)
    import time

    t0 = time.monotonic()
    result: dict[str, Any] = {"run_id": run_id, "library": library, "model": PLAN_MODEL, "max": max_n,
                              "variant": variant,
                              "session_id": tracing.session_id(), "proposals": [], "accepted": [], "rejected": [],
                              "error": None}
    try:
        with tracing.worker("trueup-planner") as span:
            _plan(root, library, max_n, client, result, out, untraced, save, variant, save_dir, run_id)
            tracing.set_verdict(span, f"accepted {len(result['accepted'])}, rejected {len(result['rejected'])}")
    except ModelError as e:
        result["error"] = str(e)
        out(f"planner stopped: {e}")
    finally:
        record_spend(run_dir, "after", client)
        spend = json.loads((run_dir / "spend.json").read_text())
        result["usage"], result["cost_usd"] = spend.get("usage"), spend.get("run_cost_usd")
        result["wall_s"] = round(time.monotonic() - t0, 1)
        result["traces_opened"] = tracing.opened()
        (run_dir / "plan.json").write_text(json.dumps(result, indent=1, default=str))
        with State(root) as state:
            state.finish_run(run_id, "error" if result["error"] else "complete")
    out(f"proposals: {len(result['proposals'])}  accepted: {len(result['accepted'])}  "
        f"rejected: {len(result['rejected'])}")
    for r in result["rejected"]:
        out(f"  rejected {r['id']}: {'; '.join(r['reasons'])}")
    out(f"tokens: {client.usage.input_tokens} in, {client.usage.output_tokens} out; "
        f"cost ${result['cost_usd'] if result['cost_usd'] is not None else '?'}; wrote {run_dir}")
    return result


def _plan(root: Path, library: str, max_n: int, client: ModelClient, result: dict[str, Any],
          out: Callable[[str], None], untraced: Callable[..., Any], save: bool, variant: str = "v2",
          save_dir: Path | None = None, run_id: str | None = None) -> None:
    source = wrapper_source(root, library)
    findings = latest_findings(root, library)
    out(f"planning for {library}: {len(source)} chars of wrapper source, {len(findings)} findings")
    initial = None
    if run_id:
        with State(root) as state:
            initial = state.observation(run_id, "planner:initial")
    if initial:
        props = initial["proposals"]
        out("resumed initial proposal batch from state.db")
    else:
        reply = client.chat_json(PLAN_MODEL, first_prompt(library, source, findings, max_n, variant),
                                 lenient=variant == "v2")
        props = reply.get("proposals") if isinstance(reply, dict) else None
        if isinstance(props, list) and run_id:
            with State(root) as state:
                state.save_observation(run_id, "planner:initial", {"status": "complete", "proposals": props})
    if not isinstance(props, list):
        raise ModelError('model reply has no "proposals" list; stopping the planner')
    existing = prop.load()
    taken = {(s.app, s.model) for s in existing}
    ids = {s.id for s in existing}
    for index, p in enumerate(props[:max_n]):
        saved = None
        if run_id:
            with State(root) as state:
                saved = state.observation(run_id, f"planner:proposal:{index}")
        if saved:
            result["proposals"].append(saved["proposal"])
            result[saved["decision"]].append(saved["result"])
            if saved["decision"] == "accepted":
                accepted = saved["result"]["proposal"]
                taken.add((accepted["app"], accepted["model"]))
                ids.add(accepted["id"])
            out(f"  {saved['result']['id']}: resumed {saved['decision']} from state.db")
            continue
        result["proposals"].append(p)
        pid = p.get("id", "?") if isinstance(p, dict) else "?"
        history = []
        for attempt in range(REVISIONS + 1):
            reasons = check(p, taken, ids, untraced)
            if not reasons:
                break
            history.append({"proposal": p, "reasons": reasons})
            out(f"  {pid}: rejected ({'; '.join(reasons)[:200]})")
            if attempt == REVISIONS:
                break
            rev = client.chat_json(PLAN_MODEL, revision_prompt(p, reasons), lenient=variant == "v2")
            revised = rev.get("proposals") if isinstance(rev, dict) else None
            if not revised:
                history.append({"proposal": None, "reasons": ["withdrawn by the model"]})
                reasons = ["withdrawn by the model after: " + "; ".join(reasons)]
                break
            p = revised[0]
        if reasons:
            decided = {"id": pid, "reasons": reasons, "tries": len(history), "history": history}
            result["rejected"].append(decided)
            if run_id:
                with State(root) as state:
                    state.save_observation(run_id, f"planner:proposal:{index}",
                                           {"status": "complete", "decision": "rejected",
                                            "proposal": result["proposals"][-1], "result": decided})
            continue
        taken.add((p["app"], p["model"]))
        ids.add(p["id"])
        path = prop.save(p, library, save_dir) if save else None
        decided = {"id": p["id"], "revisions": len(history), "proposal": p,
                   "path": str(path) if path else None}
        result["accepted"].append(decided)
        if run_id:
            with State(root) as state:
                state.save_observation(run_id, f"planner:proposal:{index}",
                                       {"status": "complete", "decision": "accepted",
                                        "proposal": result["proposals"][-1], "result": decided})
        out(f"  {p['id']}: accepted{f' after {len(history)} revision(s)' if history else ''}")
