"""trueup fix <finding-id>: locate the wrapper, let the model draft a patch and a test, and verify it.

Steps, one library at a time:
  1. locate (trueup.fixer.locate): shallow clone in .trueup/clones/<lib>; Entire's code graph if it
     is there, else ripgrep + ast; locate.json in the run dir and in fixes/<id>/
  2. baseline (verifier): the target packages' own test suites on the clean clone, and the full
     scenario library in .trueup/venvs/<lib>-fix built from the clean clone
  3. up to MAX_TRIES tries: the model drafts edits + a test (trueup.fixer.patch); code applies them;
     the verifier checks that the new test fails before and passes after, the suites show no new
     failure, the finding's scenarios now match truth, and the full library shows no new mismatch.
     A failed try goes back to the model with the reason.
Writes fixes/<id>/: patch.diff, the test file, before-after.md/json, suites.json, locate.json,
tries.json and summary.md. Nothing is committed, pushed or posted. The clone is reset at the end.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from trueup import tracing
from trueup.fixer import locate as loc
from trueup.fixer import patch as pt
from trueup.fixer import targets as tg
from trueup.fixer import verify as vf
from trueup.model import PLAN_MODEL, ModelClient, ModelError, record_spend
from trueup.state import State

MAX_TRIES = 3


def find_finding(root: Path, finding_id: str) -> tuple[dict[str, Any], Path]:
    """The finding with this id, from the newest findings.json that has it. The id names the library,
    check, field and code path, so the same id in other checked runs (other scenarios, such as
    planner proposals) is the same finding: their scenarios and leads are added to it."""
    found: list[tuple[dict[str, Any], Path]] = []
    for f in sorted((root / ".trueup" / "runs").glob("*/findings.json"), reverse=True):
        found += [(x, f.parent) for x in json.loads(f.read_text())["findings"] if x["id"] == finding_id]
    if not found:
        raise FileNotFoundError(f"no finding {finding_id!r} in .trueup/runs/*/findings.json")
    finding, run_dir = json.loads(json.dumps(found[0][0])), found[0][1]
    d = finding["details"]
    d["runs"] = {sid: run_dir.name for sid in d["scenarios"]}
    for other, odir in found[1:]:
        for sid in other["details"]["scenarios"]:
            if sid not in d["scenarios"]:
                d["scenarios"].append(sid)
                d["runs"][sid] = odir.name
        d["leads"] += [m for m in other["details"].get("leads", []) if m["scenario"] not in
                       {x["scenario"] for x in d["leads"]}]
    return finding, run_dir


def all_scenarios() -> list[str]:
    from trueup.scenarios import select
    from trueup.scenarios.proposed import load

    return [s.id for s in select("all")] + [s.id for s in load()]


def _touched(target: tg.Target, files: list[str]) -> list[tg.Package]:
    return [p for p in target.packages if any(f.startswith(p.path.strip("./") + "/" if p.path != "." else "")
                                              for f in files)]


def _short(s: str, n: int = 600) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."


def baseline(root: Path, clone: Path, commit: str, target: tg.Target, fix_dir: Path,
             out: Callable[[str], None]) -> dict[str, Any]:
    """Suites and sweep on the clean clone. Cached in fix_dir per commit."""
    cache = fix_dir / "baseline.json"
    if cache.exists():
        b = json.loads(cache.read_text())
        if b.get("commit") == commit and all(vf.baseline_usable(s)[0] for s in b["suites"].values()):
            out("baseline: cached for this commit")
            return b
    suites = {}
    for p in target.packages:
        out(f"baseline: {p.path} test venv and test suite (clean clone)")
        tpy = vf.ensure_test_venv(root, clone, target.library, p)
        suites[p.path] = vf.run_pytest(tpy, clone, p, [p.tests])
        s = suites[p.path]
        out(f"  {s.get('passed', '?')} passed, {s.get('failed', '?')} failed, {s.get('errors', '?')} errors, "
            f"exit {s['exit']}")
        ok, why = vf.baseline_usable(s)
        if not ok:
            raise vf.VerifyError(f"{p.path}: {why}")
    out("baseline: building the scenario venv from the clean clone")
    fpy = vf.ensure_fix_venv(root, clone, target.library)
    vf.reinstall(fpy, clone, target)
    out("baseline: full scenario library")
    sweep = vf.sweep_scenarios(fpy, target.library, all_scenarios(), out=out)
    b = {"commit": commit, "suites": suites, "sweep": sweep}
    loc.save(cache, json.dumps(b, indent=1, default=str))
    return b


def verify_try(root: Path, clone: Path, target: tg.Target, finding: dict[str, Any], draft: dict[str, Any],
               writes: list[dict[str, str]], base: dict[str, Any], out: Callable[[str], None],
               variant: str = "v1") -> dict[str, Any]:
    """Apply the try to the clean clone step by step. Returns the try's record with ok and reason."""
    rec: dict[str, Any] = {"ok": False}
    test = draft["test"]
    pkg_of_test = next(p for p in target.packages if test["file"].startswith(
        (p.path.strip("./") + "/" if p.path != "." else "") + p.tests + "/"))
    test_rel = str(Path(test["file"]).relative_to(pkg_of_test.path)) if pkg_of_test.path != "." else test["file"]
    tpy = vf.ensure_test_venv(root, clone, target.library, pkg_of_test)
    loc.reset_clone(clone)
    pt.write_files(clone, [{"file": test["file"], "content": test["content"]}])
    out("  new test on the unpatched code")
    t_before = vf.run_pytest(tpy, clone, pkg_of_test, [test_rel])
    pt.write_files(clone, writes)
    out("  new test on the patched code")
    t_after = vf.run_pytest(tpy, clone, pkg_of_test, [test_rel])
    ok, why = vf.new_test_verdict(t_before, t_after, variant)
    rec["new_test"] = {"before": t_before, "after": t_after, "ok": ok, "reason": why}
    out(f"  {why[:300]}")
    if not ok:
        rec["reason"] = why
        return rec
    rec["suites"] = {}
    for p in _touched(target, [w["file"] for w in writes] + [test["file"]]):
        out(f"  {p.path} test suite (patched)")
        after = vf.run_pytest(vf.ensure_test_venv(root, clone, target.library, p), clone, p, [p.tests])
        ok, why = vf.suite_verdict(base["suites"][p.path], after)
        rec["suites"][p.path] = {"after": after, "ok": ok, "reason": why}
        out(f"  {why[:300]}")
        if not ok:
            rec["reason"] = f"{p.path}: {why}"
            return rec
    fpy = vf.venvs.venv_dir(root, f"{target.library}-fix") / "bin" / "python"  # built by baseline()
    vf.reinstall(fpy, clone, target)
    out("  the finding's scenarios (patched)")
    scen = vf.sweep_scenarios(fpy, target.library, finding["details"]["scenarios"], out=out)
    ok, why = vf.scenario_verdict(scen, finding)
    rec["scenarios"] = {"ok": ok, "reason": why}
    out(f"  {why}")
    if not ok:
        rec["reason"] = why
        return rec
    out("  full scenario library (patched)")
    full = vf.sweep_scenarios(fpy, target.library, all_scenarios(), out=out)
    new = vf.new_mismatches(base["sweep"], full)
    rec["sweep"] = {"totals": vf.totals(full), "new_mismatches": new}
    rec["sweep_after"] = full
    if new:
        rec["reason"] = (f"{len(new)} new mismatch(es) in the full scenario library: " +
                         "; ".join(f"{m['scenario']} {m['check']} {m['field']}: truth {m['truth']}, trace "
                                   f"{m['trace']}" for m in new[:8]))
        out(f"  {rec['reason'][:300]}")
        return rec
    ok, why = vf.scenario_verdict(full, finding)
    rec.update(ok=ok, reason=why if ok else f"full sweep: {why}")
    return rec


def fix(root: Path, finding_id: str, *, client: ModelClient | None = None, run_id: str | None = None,
        out: Callable[[str], None] = print, max_tries: int = MAX_TRIES, variant: str = "v2",
        out_dir: Path | None = None) -> dict[str, Any]:
    """out_dir: write there instead of fixes/<id>/ (the v1/v2 comparison runs do, so the committed fix
    stays as it was verified). The baseline cache of fixes/<id>/ is reused."""
    from trueup.sweep import new_run_id

    finding, found_in = find_finding(root, finding_id)
    target = tg.get(finding["library"], finding["details"]["code_path"])
    run_id = run_id or new_run_id(f"fix-{finding['library']}")
    run_dir = root / ".trueup" / "runs" / run_id
    fix_dir = out_dir or root / "fixes" / finding_id
    run_dir.mkdir(parents=True, exist_ok=True)
    fix_dir.mkdir(parents=True, exist_ok=True)
    # Once a fix has proof artifacts, a later failed experiment may only add a
    # runs/<id>.json record.  All temporary locate/baseline files live with the
    # run, so the proven directory remains byte-for-byte unchanged.
    proven = all((fix_dir / name).exists() for name in ("patch.diff", "before-after.json", "before-after.md"))
    work_dir = run_dir / "candidate" if proven and out_dir is None else fix_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    with State(root) as state:
        state.begin_run(run_id, "fix", finding_id)
    cached = root / "fixes" / finding_id / "baseline.json"
    if out_dir and cached.exists() and not (fix_dir / "baseline.json").exists():
        (fix_dir / "baseline.json").write_text(cached.read_text())
    t0 = time.monotonic()
    for stale in [work_dir / "patch.diff", *work_dir.glob("before-after.*"), *work_dir.glob("test_trueup_*.py")]:
        stale.unlink(missing_ok=True)  # a run that does not fix must not leave an earlier patch behind
    client = client or ModelClient()
    record_spend(run_dir, "before", client)
    result: dict[str, Any] = {"finding": finding_id, "title": finding["title"], "library": target.library,
                              "found_in": found_in.name, "run_id": run_id, "session_id": tracing.session_id(),
                              "model": PLAN_MODEL, "variant": variant,
                              "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "tries": [], "fixed": False, "error": None}
    clone = None
    try:
        with tracing.worker("trueup-fixer", step="locate") as span:
            located = loc.locate(root, target, run_dir, finding=finding)
            clone = Path(located["clone"])
            loc.reset_clone(clone)
            loc.save((work_dir / "locate.json"), (run_dir / "locate.json").read_text())
            result["commit"], result["locate_method"] = located["commit"], located["method"]
            out(f"located with {located['method']}: {len(located['definitions'])} definitions, "
                f"{len(located['callers'])} callers ({located['graph'].get('reason', '')[:160]})")
            tracing.set_verdict(span, located["method"])
        with tracing.worker("trueup-verifier", step="baseline") as span:
            if proven and (fix_dir / "baseline.json").exists() and not (work_dir / "baseline.json").exists():
                loc.save(work_dir / "baseline.json", (fix_dir / "baseline.json").read_text())
            base = baseline(root, clone, located["commit"], target, work_dir, out)
            tracing.set_verdict(span, f"baseline: {vf.totals(base['sweep'])['leads']} leads")
        result["suites_before"] = {k: {x: v.get(x) for x in ("total", "passed", "failed", "errors", "skipped",
                                                              "failing", "exit")} for k, v in base["suites"].items()}
        messages = pt.first_prompt(finding, target, located, loc.source_excerpts(clone, located),
                                   pt.test_style(clone, target), pt.span_summary(
            sorted({found_in.parent / n for n in finding["details"]["runs"].values()}), finding), variant)
        first = messages
        for n in range(1, max_tries + 1):
            with State(root) as state:
                saved_try = state.observation(run_id, f"fixer:try:{n}")
            if saved_try:
                rec = saved_try["result"]
                result["tries"].append(rec)
                out(f"try {n}: resumed {'PASS' if rec['ok'] else 'FAIL'} from state.db")
                if rec["ok"]:
                    result["fixed"] = True
                    if not (fix_dir / "patch.diff").exists():
                        write_fix(fix_dir, finding, target, base, rec)
                    break
                draft = rec.get("draft")
                if variant == "v2":
                    messages = pt.revision_prompt_v2(first, draft, rec["reason"],
                                                     [t["reason"] for t in result["tries"][:-1]])
                else:
                    messages = pt.revision_prompt(messages, draft, rec["reason"])
                continue
            out(f"try {n}/{max_tries}: asking {PLAN_MODEL} for a patch")
            rec: dict[str, Any] = {"try": n}
            with tracing.worker("trueup-fixer", step=f"draft {n}") as span:
                with State(root) as state:
                    saved_draft = state.observation(run_id, f"fixer:draft:{n}")
                if saved_draft:
                    draft = saved_draft["draft"]
                    out(f"try {n}: resumed paid draft from state.db")
                else:
                    draft = checkpointed_draft(root, run_id, n, client, messages, variant)
                rec["explanation"] = draft.get("explanation") if isinstance(draft, dict) else None
                rec["draft"] = draft
                try:
                    loc.reset_clone(clone)  # edits are against the original files, not the last try's
                    writes = pt.check_draft(draft, clone, target)
                    tracing.set_verdict(span, "applies")
                except pt.PatchError as e:
                    rec.update(ok=False, stage="apply", reason=f"patch does not apply: {e}")
                    tracing.set_verdict(span, "does not apply")
                    tracing.mark("fix attempt failed", stage="apply", attempt=n)
            if "stage" not in rec:
                with tracing.worker("trueup-verifier", step=f"try {n}") as span:
                    rec.update(verify_try(root, clone, target, finding, draft, writes, base, out, variant))
                    rec["stage"] = "verified" if rec["ok"] else "verify"
                    rec["diff"] = pt.diff(clone)
                    tracing.set_verdict(span, "pass" if rec["ok"] else "fail")
                    if not rec["ok"]:
                        tracing.mark("fix attempt failed", stage="verify", attempt=n)
            out(f"try {n}: {'PASS' if rec['ok'] else 'FAIL'}: {_short(rec['reason'], 400)}")
            result["tries"].append(rec)
            if rec["ok"]:
                result["fixed"] = True
                write_fix(fix_dir, finding, target, base, rec)
                with State(root) as state:
                    state.save_observation(run_id, f"fixer:try:{n}",
                                           {"status": "complete", "result": rec})
                break
            with State(root) as state:
                state.save_observation(run_id, f"fixer:try:{n}", {"status": "complete", "result": rec})
            if variant == "v2":
                messages = pt.revision_prompt_v2(first, draft, rec["reason"],
                                                 [t["reason"] for t in result["tries"][:-1]])
            else:
                messages = pt.revision_prompt(messages, draft, rec["reason"])
    except (ModelError, vf.VerifyError, RuntimeError) as e:
        result["error"] = f"{type(e).__name__}: {e}"
        out(f"fixer stopped: {result['error']}")
    finally:
        if clone is not None:
            loc.reset_clone(clone)
        record_spend(run_dir, "after", client)
        spend = json.loads((run_dir / "spend.json").read_text())
        result["usage"], result["cost_usd"] = spend.get("usage"), spend.get("run_cost_usd")
        result["spend_after_usd"] = spend.get("after", {}).get("spend_usd")
        result["wall_s"] = round(time.monotonic() - t0, 1)
        result["traces_opened"] = tracing.opened()
        write_log(fix_dir, run_dir, result, publish=bool(result["fixed"] or not proven))
        with State(root) as state:
            state.finish_run(run_id, "fixed" if result["fixed"] else "error" if result["error"] else "not_fixed")
    out(f"{finding_id}: {'fixed, verified' if result['fixed'] else 'NOT fixed'} after {len(result['tries'])} "
        f"tr{'y' if len(result['tries']) == 1 else 'ies'}; model cost ${result['cost_usd']}; wrote {fix_dir}")
    with State(root) as state:
        status = "fixed" if result["fixed"] else "error" if result["error"] else "not_fixed"
        state.save_fix(finding_id, status, result)
    return result


def checkpointed_draft(root: Path, run_id: str, number: int, client: ModelClient,
                       messages: list[dict[str, str]], variant: str) -> Any:
    """Make one paid draft call at most once for a run/try, even across process restarts."""
    step = f"fixer:draft:{number}"
    with State(root) as state:
        saved = state.observation(run_id, step)
    if saved:
        return saved["draft"]
    draft = client.chat_json(PLAN_MODEL, messages, max_tokens=12000, lenient=variant == "v2")
    with State(root) as state:
        state.save_observation(run_id, step, {"status": "complete", "draft": draft})
    return draft


def locate_only(root: Path, finding_id: str, out: Callable[[str], None] = print) -> dict[str, Any]:
    """Re-run only the locate step (no model call, no patch). Writes fixes/<id>/locate.json and
    graph-compare.json/.md: where the functions the verified patch.diff changed rank among what the
    graph found, next to the ripgrep + ast fallback."""
    finding, _ = find_finding(root, finding_id)
    target = tg.get(finding["library"], finding["details"]["code_path"])
    fix_dir = root / "fixes" / finding_id
    fix_dir.mkdir(parents=True, exist_ok=True)
    old = fix_dir / "locate.json"
    if old.exists() and not (fix_dir / "locate-fix-run.json").exists():
        # The locate output the fix runs used (ripgrep + ast); this re-run replaces locate.json.
        loc.save(fix_dir / "locate-fix-run.json", old.read_text())
    with tracing.worker("trueup-fixer", step="locate only") as span:
        located = loc.locate(root, target, fix_dir, finding=finding)
        clone = Path(located["clone"])
        loc.reset_clone(clone)
        fallback = loc.locate_symbols(clone, target)
        tracing.set_verdict(span, located["method"])
    diff = fix_dir / "patch.diff"
    patched = loc.patched_functions(clone, diff.read_text()) if diff.exists() else []
    res = {"finding": finding_id, "commit": located["commit"], "method": located["method"],
           "graph_reason": located["graph"].get("reason"), "query": located["graph"].get("query"),
           "patched_functions": patched,
           "graph": loc.compare_with_patch(located, patched) if located["graph"]["used"] else None,
           "fallback": loc.compare_with_patch({**fallback, "definitions": [
               {**d, "rank": i} for i, d in enumerate(fallback["definitions"], 1)]}, patched),
           "graph_top": [{"rank": d["rank"], "qualname": d["qualname"], "file": d["file"], "score": d["score"]}
                         for d in located["definitions"][:8]] if located["graph"]["used"] else []}
    loc.save(fix_dir / "graph-compare.json", json.dumps(res, indent=1))
    loc.save(fix_dir / "graph-compare.md", compare_md(res))
    out(compare_md(res))
    return res


def compare_md(res: dict[str, Any]) -> str:
    lines = [f"# Locate re-run: {res['finding']}", "",
             f"Method: {res['method']} ({res['graph_reason']}). Clone commit {res['commit'][:10]}.",
             f"Query: {res['query']}" if res["query"] else "", "",
             "| patched function | file | graph rank | ripgrep + ast rank | among graph callers |", "|---|---|---|---|---|"]
    fb = {(r["file"], r["qualname"]): r for r in res["fallback"]["patched"]}

    def rank(r: dict[str, Any]) -> str:
        if r["rank"] is not None:
            return str(r["rank"])
        return f"only its class, at {r['class_rank']}" if r.get("class_rank") else "not found"

    for r in (res["graph"] or res["fallback"])["patched"]:
        lines.append(f"| {r['qualname']} | {r['file']} | {rank(r) if res['graph'] else '-'} | "
                     f"{rank(fb[(r['file'], r['qualname'])])} | "
                     f"{'yes' if res['graph'] and r['among_callers'] else 'no'} |")
    if res["graph"]:
        g = res["graph"]
        lines += ["", f"Graph found {g['found']} of {len(g['patched'])} patched functions, {g['in_top']} in its top "
                      f"{g['top']} (the ones followed up with neighbors and impact). Ranked first: "
                      f"{'yes' if g['same_function_first'] else 'no'}.", "", "Graph top hits:", ""]
        lines += [f"{d['rank']}. {d['qualname']} ({d['file']}, score {d['score']})" for d in res["graph_top"]]
    return "\n".join(lines) + "\n"


def write_fix(fix_dir: Path, finding: dict[str, Any], target: tg.Target, base: dict[str, Any],
              rec: dict[str, Any]) -> None:
    loc.save((fix_dir / "patch.diff"), rec["diff"])
    test = rec["draft"]["test"]
    loc.save((fix_dir / Path(test["file"]).name), test["content"])
    rows = vf.before_after(finding, base["sweep"], rec["sweep_after"])
    tb, ta = vf.totals(base["sweep"]), vf.totals(rec["sweep_after"])
    loc.save((fix_dir / "before-after.json"), json.dumps({"rows": rows, "before": tb, "after": ta}, indent=1,
                                                          default=str))
    loc.save((fix_dir / "before-after.md"), vf.table_md(rows, tb, ta))


def write_log(fix_dir: Path, run_dir: Path, result: dict[str, Any], *, publish: bool = True) -> None:
    tries = []
    for t in result["tries"]:
        t = {k: v for k, v in t.items() if k != "sweep_after"}
        tries.append(t)
    log = {**result, "tries": tries}
    loc.save((run_dir / "fix.json"), json.dumps(log, indent=1, default=str))
    # Every run's tries are kept, also the runs that did not fix it.
    (fix_dir / "runs").mkdir(exist_ok=True)
    loc.save((fix_dir / "runs" / f"{result['run_id']}.json"), json.dumps(log, indent=1, default=str))
    if not publish:
        return
    loc.save((fix_dir / "tries.json"), json.dumps(log, indent=1, default=str))
    suites = {"before": result.get("suites_before", {}),
              "after": {n: {p: {x: s["after"].get(x) for x in ("total", "passed", "failed", "errors", "skipped",
                                                                  "failing", "exit")} | {"verdict": s["reason"]}
                            for p, s in t.get("suites", {}).items()} for n, t in
                        ((t["try"], t) for t in result["tries"])}}
    loc.save((fix_dir / "suites.json"), json.dumps(suites, indent=1, default=str))
    lines = [f"# {result['finding']}", "", result["title"], "",
             f"Library commit: {result.get('commit', '?')}. Located with {result.get('locate_method', '?')}.",
             f"Model: {result['model']}; cost ${result['cost_usd']} (key spend delta); run {result['run_id']}.", "",
             "Result: " + ("fixed: the new test fails before and passes after, the suites show no new failure, the "
                           "finding's scenarios match truth and the full scenario library has no new mismatch."
                           if result["fixed"] else "NOT fixed. No patch is offered."
                           + (f" Stopped: {result['error']}" if result["error"] else "")), "", "## Tries", ""]
    for t in result["tries"]:
        lines.append(f"{t['try']}. {'PASS' if t['ok'] else 'FAIL'} at {t.get('stage')}: {_short(t['reason'], 700)}")
        if t.get("explanation"):
            lines.append(f"   Model's explanation: {_short(t['explanation'], 500)}")
    if (fix_dir / "before-after.md").exists() and result["fixed"]:
        lines += ["", "## Before and after", "", (fix_dir / "before-after.md").read_text()]
    loc.save((fix_dir / "summary.md"), "\n".join(lines) + "\n")


def reprove(root: Path, finding_id: str, out: Callable[[str], None] = print) -> dict[str, Any]:
    """Apply the committed fixes/<id>/patch.diff to the clean clone and sweep the full scenario library
    again (no model call). Writes fixes/<id>/proof.json: every lead before (the fix's baseline) and after,
    and the finding's scenarios' observations after the patch, so the counts can be recomputed."""
    import subprocess

    from trueup.runner import run_scenario

    finding, _ = find_finding(root, finding_id)
    target = tg.get(finding["library"], finding["details"]["code_path"])
    fix_dir = root / "fixes" / finding_id
    base = json.loads((fix_dir / "baseline.json").read_text())
    clone, commit = loc.ensure_clone(root, target.library)
    if commit != base["commit"]:
        raise RuntimeError(f"clone is at {commit[:10]}, the fix was verified at {base['commit'][:10]}")
    loc.reset_clone(clone)
    p = subprocess.run(["git", "-C", str(clone), "apply", str((fix_dir / "patch.diff").resolve())],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"patch.diff does not apply: {p.stderr.strip()[-300:]}")
    observations: dict[str, Any] = {}

    def run(py: Path, library: str, sid: str) -> dict[str, Any]:
        r = run_scenario(py, library, sid)
        if sid in finding["details"]["scenarios"] and r.get("observation"):
            observations[sid] = r["observation"]
        return r

    try:
        fpy = vf.venvs.venv_dir(root, f"{target.library}-fix") / "bin" / "python"
        vf.reinstall(fpy, clone, target)
        out("patched: full scenario library")
        after = vf.sweep_scenarios(fpy, target.library, all_scenarios(), run=run, out=out)
    finally:
        loc.reset_clone(clone)
        vf.reinstall(vf.venvs.venv_dir(root, f"{target.library}-fix") / "bin" / "python", clone, target)
    keep = ("check", "field", "severity", "truth", "trace")
    proof = {"finding": finding_id, "commit": commit,
             "before": {"leads": {s: [{k: m.get(k) for k in keep} for m in ls] for s, ls in base["sweep"]["leads"].items()},
                        "not_run": base["sweep"]["not_run"]},
             "after": {"leads": {s: [{k: m.get(k) for k in keep} for m in ls] for s, ls in after["leads"].items()},
                       "not_run": after["not_run"]},
             "rows": vf.before_after(finding, base["sweep"], after),
             "new_mismatches": vf.new_mismatches(base["sweep"], after),
             "after_observations": observations}
    loc.save(fix_dir / "proof.json", json.dumps(proof, indent=1, default=str))
    tb, ta = vf.totals(base["sweep"]), vf.totals(after)
    out(f"before {tb}; after {ta}; new mismatches {len(proof['new_mismatches'])}")
    return proof
