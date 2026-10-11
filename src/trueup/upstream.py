"""trueup upstream <finding-id>: draft issue and PR text into upstream/<finding-id>/. Never posts.

The text is built from recorded data: the finding, the fix's before/after table and suite results
(fixes/<id>/), the scenarios on the same code path that are right (the boundary), and a standalone
repro that needs only the library and the provider SDK (httpx.MockTransport answers; no keys, no
network). The repro is run here, on the latest release and on the clone with patch.diff applied,
and its output goes into the text. The issue follows the repo's issue template when it has one.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from trueup.core.repro import line_count
from trueup.fix import find_finding
from trueup.fixer import locate as loc
from trueup.fixer import targets as tg
from trueup.fixer import verify as vf
from trueup.fixer.patch import code_path_prefix
from trueup.runner import venvs
from trueup.runner.setups import VERSIONED

MAX_REPRO_LINES = 40

_AGENTS_BODY = '''BODY = {"id": "resp_1", "object": "response", "created_at": 0, "status": "completed", "model": "m",
        "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "Hello!", "annotations": []}]}],
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
        "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}'''

REPROS: dict[tuple[str, str], str] = {
    ("openllmetry", "openai-agents"): '''"""OpenLLMetry + OpenAI Agents SDK: one model call is recorded as two LLM spans.
Needs traceloop-sdk and openai-agents. Offline: httpx.MockTransport answers. Leave OPENAI_API_KEY
unset so the Agents SDK's own exporter skips its upload."""
import asyncio

import httpx
from openai import AsyncOpenAI
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from traceloop.sdk import Traceloop

exporter = InMemorySpanExporter()
Traceloop.init(app_name="repro", exporter=exporter, disable_batch=True, telemetry_enabled=False)
from agents import Agent, OpenAIResponsesModel, Runner  # noqa: E402

''' + _AGENTS_BODY + '''
transport = httpx.MockTransport(lambda request: httpx.Response(200, json=BODY))
client = AsyncOpenAI(api_key="x", base_url="http://fake/v1", http_client=httpx.AsyncClient(transport=transport))
agent = Agent(name="helper", model=OpenAIResponsesModel("m", client))
asyncio.run(Runner.run(agent, "hi"))
llm = [s for s in exporter.get_finished_spans() if s.attributes.get("gen_ai.operation.name") == "chat"]
tokens = sum(s.attributes.get("gen_ai.usage.output_tokens", 0) for s in llm)
print(f"provider requests: 1; LLM spans: {len(llm)}; output tokens on LLM spans: {tokens} (provider sent 7)")
''',
    ("openinference", "openai-agents"): '''"""OpenInference + OpenAI Agents SDK: a run that raises leaves the top-level span OK.
Needs openinference-instrumentation-openai-agents and openai-agents. Offline: httpx.MockTransport
answers HTTP 500. Leave OPENAI_API_KEY unset so the Agents SDK's own exporter skips its upload."""
import asyncio

import httpx
from openai import AsyncOpenAI
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
OpenAIAgentsInstrumentor().instrument(tracer_provider=provider)
from agents import Agent, OpenAIResponsesModel, Runner  # noqa: E402

transport = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": {"message": "boom"}}))
client = AsyncOpenAI(api_key="x", base_url="http://fake/v1", max_retries=0,
                     http_client=httpx.AsyncClient(transport=transport))
agent = Agent(name="helper", model=OpenAIResponsesModel("m", client))
try:
    asyncio.run(Runner.run(agent, "hi"))
except Exception as e:
    print(f"the run raised {type(e).__name__}")
root = next(s for s in exporter.get_finished_spans() if s.parent is None)
print(f"top-level span {root.name!r}: {root.status.status_code.name}")
''',
    ("neatlogs", "anthropic messages stream"): '''"""neatlogs + Anthropic messages.stream(): a stream that fails leaves the span OK.
Needs neatlogs and anthropic. Offline: httpx.MockTransport answers with an SSE stream that ends in an
error event; export is off. anthropic 1.x uses httpx2 instead of httpx."""
import json

import anthropic
import httpx2 as httpx
import neatlogs
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter, provider = InMemorySpanExporter(), TracerProvider()
neatlogs.init(api_key="x", instrumentations=["anthropic"], disable_export=True, tracer_provider=provider)
provider.add_span_processor(SimpleSpanProcessor(exporter))
start = {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "m",
         "content": [], "stop_reason": None, "usage": {"input_tokens": 5, "output_tokens": 0}}}
error = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
sse = "".join(f"event: {e['type']}\\ndata: {json.dumps(e)}\\n\\n" for e in (start, error))
transport = httpx.MockTransport(lambda r: httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"}))
client = anthropic.Anthropic(api_key="x", base_url="http://fake", http_client=httpx.Client(transport=transport))
try:
    with client.messages.stream(model="m", max_tokens=16, messages=[{"role": "user", "content": "hi"}]) as s:
        "".join(s.text_stream)
except Exception as e:
    print(f"the app saw {type(e).__name__}")
neatlogs.flush()
for span in exporter.get_finished_spans():
    print(f"span {span.name!r}: {span.status.status_code.name}, exception events: "
          f"{sum(e.name == 'exception' for e in span.events)}")
''',
}

# Per library: the template's component, the PR title prefix and the issue template file.
META = {
    ("openllmetry", "openai-agents"): {
        "component": "OpenAI Instrumentation", "pr_title": "fix(openai-agents): record one LLM span per model call",
        "title": "OpenAI Agents SDK: every non-streamed model call is recorded as two LLM spans (calls and tokens "
                 "doubled)",
        "expected": "One LLM span per model call (OTel GenAI conventions), with the tokens the provider sent.",
        "pr_note": ("The new test functions that also pass without the patch guard the change but do not show "
                    "the bug; the scenario table and the repro are the end-to-end proof.")},
    ("openinference", "openai-agents"): {
        "pr_title": "fix(openai-agents): set the root span to ERROR when the agent run fails",
        "title": "openai-agents: a run that raises leaves the top-level span OK",
        "expected": ("The top-level span is ERROR when the run raises (a span whose operation failed has status "
                     "ERROR). A run whose tool raised but which still finished stays OK."),
        "pr_note": ("Limit: any ERROR on a non-function span marks the run ERROR, so a span error the SDK later "
                    "recovers from would also mark the root ERROR. No such case is in Trueup's scenarios.")},
    ("neatlogs", "anthropic messages stream"): {
        "pr_title": "fix(anthropic): record an error on messages.stream() spans when the stream fails",
        "title": "Anthropic messages.stream(): a stream that fails (error event or cut connection) is recorded as OK",
        "expected": ("The span is ERROR with an exception event, as neatlogs already records for "
                     "messages.create(stream=True)."),
        "pr_note": "On failure the span gets the error and ends; partial text and tokens are not recorded."},
}


def run_repro(py: Path, script: str, timeout: float = 180) -> dict[str, Any]:
    env = vf.test_env()
    env.pop("OPENAI_API_KEY", None)  # the Agents SDK's own exporter then skips its upload
    with tempfile.TemporaryDirectory(prefix="trueup-upstream-") as tmp:
        f = Path(tmp) / "repro.py"
        f.write_text(script)
        try:
            p = subprocess.run([str(py), str(f)], cwd=tmp, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"exit": -1, "stdout": "", "stderr": f"timed out after {timeout:.0f} s"}
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    return {"exit": p.returncode, "stdout": ansi.sub("", p.stdout).strip(), "stderr": ansi.sub("", p.stderr).strip()[-1500:]}


def versions(py: Path, library: str) -> dict[str, str]:
    code = ("import json, importlib.metadata as m\nout = {}\nfor d in " + json.dumps(VERSIONED[library]) +
            ":\n    try: out[d] = m.version(d)\n    except Exception: pass\nprint(json.dumps(out))")
    p = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=60)
    return json.loads(p.stdout) if p.returncode == 0 else {}


def boundary(finding: dict[str, Any], fix_dir: Path) -> dict[str, list[str]]:
    """Scenarios on the same code path (id prefix) that are right before the patch, from the fix's baseline."""
    base = json.loads((fix_dir / "baseline.json").read_text())["sweep"] if (fix_dir / "baseline.json").exists() \
        else {"leads": {}}
    d = finding["details"]
    prefixes = tuple({code_path_prefix(sid) for sid in d["scenarios"]})
    same = [sid for sid in base["leads"] if sid.startswith(prefixes)]
    right = [sid for sid in same if sid not in d["scenarios"] and not any(
        vf.matches_finding(m, finding) for m in base["leads"][sid])]
    return {"affected": d["scenarios"], "right": right}


def patched_python(root: Path, target: tg.Target, fix_dir: Path) -> tuple[Path | None, str]:
    """The -fix venv with patch.diff applied to the clean clone and installed. (None, reason) if no fix."""
    diff = fix_dir / "patch.diff"
    if not diff.exists():
        return None, "no verified fix in fixes/ for this finding"
    clone, _ = loc.ensure_clone(root, target.library)
    loc.reset_clone(clone)
    p = subprocess.run(["git", "-C", str(clone), "apply", str(diff.resolve())], capture_output=True, text=True)
    if p.returncode != 0:
        loc.reset_clone(clone)
        return None, f"patch.diff does not apply to the clone: {p.stderr.strip()[-300:]}"
    try:
        py = venvs.venv_dir(root, f"{target.library}-fix") / "bin" / "python"
        if not py.exists():
            py = vf.ensure_fix_venv(root, clone, target.library)
        vf.reinstall(py, clone, target)
    finally:
        loc.reset_clone(clone)
    return py, "patched"


def upstream(root: Path, finding_id: str, out: Any = print) -> Path:
    finding, _ = find_finding(root, finding_id)
    key = (finding["library"], finding["details"]["code_path"])
    target = tg.get(*key)
    script = REPROS[key]
    n = line_count(script)
    if n >= MAX_REPRO_LINES:
        raise ValueError(f"the repro has {n} lines; it must be under {MAX_REPRO_LINES}")
    fix_dir = root / "fixes" / finding_id
    up_dir = root / "upstream" / finding_id
    up_dir.mkdir(parents=True, exist_ok=True)
    fix = json.loads((fix_dir / "tries.json").read_text()) if (fix_dir / "tries.json").exists() else None
    out("running the repro on the latest release")
    before_py = venvs.ensure(root, target.library)
    before = run_repro(before_py, script)
    if before["exit"] != 0:
        raise ValueError(f"the repro failed on the latest release (exit {before['exit']}): {before['stderr'][-400:]}")
    after_py, why = patched_python(root, target, fix_dir) if fix and fix.get("fixed") else (None, "no verified fix")
    out(f"running the repro on the patched clone ({why})")
    after = run_repro(after_py, script) if after_py else None
    env = {"python": platform.python_version(), "os": f"{platform.system()} {platform.machine()}",
           "latest release": versions(before_py, target.library),
           "patched": {"commit": fix.get("commit") if fix else None, "packages": [p.path for p in target.packages]}}
    data = {"finding": finding_id, "repro_lines": n, "before": before, "after": after, "after_note": why,
            "environment": env, "boundary": boundary(finding, fix_dir), "fixed": bool(fix and fix.get("fixed")),
            "posted": False}
    loc.save((up_dir / "repro.py"), script)
    loc.save((up_dir / "repro-output.json"), json.dumps(data, indent=1))
    loc.save((up_dir / "issue.md"), issue_text(root, finding, target, data, fix_dir))
    loc.save((up_dir / "pr.md"), pr_text(finding, target, data, fix_dir, fix))
    out(f"repro ({n} lines) before: {before['stdout'] or before['stderr'][-200:]}")
    if after:
        out(f"repro after the patch: {after['stdout'] or after['stderr'][-200:]}")
    out(f"wrote {up_dir} (nothing posted)")
    return up_dir


def _code(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text.rstrip()}\n```"


def _sections(finding: dict[str, Any], target: tg.Target, data: dict[str, Any], fix_dir: Path) -> dict[str, str]:
    d = finding["details"]
    b = data["boundary"]
    table = (fix_dir / "before-after.md").read_text() if (fix_dir / "before-after.md").exists() else ""
    rows = "\n".join(f"- `{x['scenario']}`: {x['field']} should be {x['truth']}, the trace has {x['trace']}"
                     for x in d.get("leads", []))
    return {
        "symptom": (f"Trueup ran each case against a fake provider, so it knows what really happened, and compared that with the exported spans:\n\n"
                    f"{rows}"),
        "boundary": (f"Affected: {', '.join(f'`{s}`' for s in b['affected'])}.\n\nRight today on the same code "
                     f"path: {', '.join(f'`{s}`' for s in b['right']) or 'none'}.\n\nChecked on: "
                     f"{d.get('rules', {}).get('latest_and_main', '?')}."),
        "repro": (f"Standalone, {data['repro_lines']} lines, needs only the library and the SDK; no API key, no "
                  f"network:\n\n{_code(REPROS[(target.library, target.code_path)], 'python')}\n\nOutput on the "
                  f"latest release:\n\n{_code(data['before']['stdout'] or data['before']['stderr'])}"),
        "expected": META[(target.library, target.code_path)]["expected"],
        "table": table,
        "environment": (f"Python {data['environment']['python']}, {data['environment']['os']}. Versions: " +
                        ", ".join(f"{k} {v}" for k, v in data["environment"]["latest release"].items()) + "."),
        "dedupe": "; ".join(f"`{s['query']}` ({s['hits']} hits, {s['date'][:10]})"
                            for s in finding.get("dedupe", {}).get("searches", [])),
    }


def issue_text(root: Path, finding: dict[str, Any], target: tg.Target, data: dict[str, Any], fix_dir: Path) -> str:
    s = _sections(finding, target, data, fix_dir)
    meta = META[(target.library, target.code_path)]
    note = "<!-- Drafted by Trueup from recorded runs. Not posted. -->\n\n"
    if target.library == "openllmetry":  # .github/ISSUE_TEMPLATE/bug_report.yml
        return note + "\n\n".join([
            f"# 🐛 Bug Report: {meta['title']}",
            f"### Which component is this bug for?\n\n{meta['component']} (the fix is in "
            "opentelemetry-instrumentation-openai-agents and opentelemetry-instrumentation-openai)",
            f"### 📜 Description\n\n{s['symptom']}\n\n{s['boundary']}",
            f"### 👟 Reproduction steps\n\n{s['repro']}",
            f"### 👍 Expected behavior\n\n{s['expected']}",
            f"### 👎 Actual Behavior with Screenshots\n\n{s['table'] or 'See the repro output.'}",
            f"### 🤖 Python Version\n\n{data['environment']['python']}",
            f"### 📃 Provide any additional context for the Bug.\n\n{s['environment']}",
            f"### 👀 Have you spent some time to check if this bug has been raised before?\n\n- [x] I checked and "
            f"didn't find similar issue (searched issues and PRs in all states: {s['dedupe']})",
            "### Are you willing to submit PR?\n\nYes I am willing to submit a PR!"])
    if target.library == "openinference":  # .github/ISSUE_TEMPLATE/bug_report.md
        return note + "\n\n".join([
            f"# [bug] {meta['title']}",
            f"**Describe the bug**\n\n{s['symptom']}\n\n{s['boundary']}",
            f"**To Reproduce**\n\n{s['repro']}",
            f"**Expected behavior**\n\n{s['expected']}",
            "**Screenshots**\n\nNone; the repro prints the span status.",
            f"**Environment**\n\n{s['environment']}",
            f"**Additional context**\n\nBefore and after the proposed fix, from Trueup's runs:\n\n{s['table']}\n"
            f"Searched issues and PRs first: {s['dedupe']}."])
    return note + "\n\n".join([  # neatlogs has no issue template
        f"# {meta['title']}", f"## Symptom\n\n{s['symptom']}", f"## Boundary\n\n{s['boundary']}",
        f"## Repro\n\n{s['repro']}", f"## Expected\n\n{s['expected']}",
        f"## Before and after the proposed fix\n\n{s['table']}", f"## Environment\n\n{s['environment']}",
        f"Searched issues and PRs first: {s['dedupe']}."])


def pr_text(finding: dict[str, Any], target: tg.Target, data: dict[str, Any], fix_dir: Path,
            fix: dict[str, Any] | None) -> str:
    meta = META[(target.library, target.code_path)]
    head = "<!-- Drafted by Trueup from recorded runs. Not posted. -->\n\n"
    if not data["fixed"] or not fix:
        return head + f"# {meta['pr_title']}\n\nNo verified fix: {data['after_note']}. No PR is proposed.\n"
    ok = next(t for t in fix["tries"] if t["ok"])
    s = _sections(finding, target, data, fix_dir)
    suites = "\n".join(f"- `{p}`: {v['reason']}" for p, v in ok.get("suites", {}).items())
    before = "\n".join(f"- `{p}` before the patch: {v['passed']} passed, {len(v['failing'])} failing"
                       + (f" ({', '.join(t.rsplit('::', 1)[-1] for t in v['failing'])})" if v["failing"] else "")
                       for p, v in fix.get("suites_before", {}).items())
    files = sorted({ln[6:] for ln in (fix_dir / "patch.diff").read_text().splitlines() if ln.startswith("+++ b/")})
    after = data["after"]["stdout"] if data["after"] else "(not run)"
    body = [f"# {meta['pr_title']}", f"## What\n\n{ok.get('explanation') or ''}",
            "## Files\n\n" + "\n".join(f"- `{f}`" for f in files),
            f"## Test\n\n{ok['new_test']['reason']}.\n\n{meta.get('pr_note', '')}", f"## Suites\n\n{before}\n{suites}",
            f"## Before and after\n\n{s['table']}\nThe standalone repro from the issue, with this patch:\n\n"
            f"{_code(after)}"]
    if target.library == "openllmetry":  # .github/PULL_REQUEST_TEMPLATE.md
        body.append("- [x] I have added tests that cover my changes.\n- [ ] If adding a new instrumentation or "
                    "changing an existing one, I've added screenshots from some observability platform showing the "
                    "change. (Not done: the change was checked with in-memory spans, see the table.)\n- [x] PR name "
                    "follows conventional commits format: `feat(instrumentation): ...` or `fix(instrumentation): "
                    "...`.\n- [ ] (If applicable) I have updated the documentation accordingly. (Not applicable.)")
    body.append(f"Patch drafted by {fix['model']} and verified by Trueup ({len(fix['tries'])} tries in the last run; "
                "every try is in tries.json).")
    return head + "\n\n".join(body) + "\n"
