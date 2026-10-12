"""The evidence bundle (evidence/) and `trueup verify`.

`build` (trueup bundle) copies what backs each headline number out of the git-ignored .trueup/ and
fixes/ into evidence/, trimmed to what the checks need, and writes manifest.json with the sha256 of
every file. `verify` needs only evidence/: no keys, no network. It checks every sha256, re-runs the
comparer on each finding's saved truth and spans, recomputes every headline number and compares them
with headline.json. Any changed byte, missing or extra file, or number that does not follow fails it.

Layout:
  manifest.json                 sha256 of every other file
  headline.json                 the numbers the README, hackathon.md and docs/index.html quote
  runs.json                     per run: id, kind, library, variant, versions, neatlogs session id
  withdrawn.json                withdrawn leads with the rule and reason; disputed groups
  v1v2.json                     raw per-run data for the v1/v2 table and the answer key
  findings/<id>/finding.json    the finding, its rules, dedupe log and upstream draft link
  findings/<id>/scenario.json   the example scenario as data
  findings/<id>/truth.json      what really happened (truth log)
  findings/<id>/spans.json      what the library exported, trimmed
  findings/<id>/repro.py        the minimal repro
  findings/<id>/proof.json      fixed findings: every lead before and after the patch, after-spans
  findings/<id>/patch.diff, graph.json   fixed findings: the verified patch, Entire graph output
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from trueup.core import group as grp

EVIDENCE = "evidence"
REPO_URL = "https://github.com/Jennycruzy/trueup/blob/main"
PRICE = {"input": 3.0, "output": 15.0}  # USD per million tokens, claude-sonnet-4.6 list price

# Span attributes the comparer never reads: prompts, tool definitions, request headers. A bundle file
# keeps the trimmed spans only if the comparer gives the same leads on them as on the full spans.
DROP_ATTR = re.compile(r"^(input\.value|input\.mime_type|llm\.input_messages\.|gen_ai\.input\.messages|"
                       r"gen_ai\.prompt\.|gen_ai\.tool\.definitions|llm\.tools\.|gen_ai\.headers|"
                       r"llm\.invocation_parameters|traceloop\.entity\.input|neatlogs\.llm\.prompts\.|metadata)")

# The run ids the v1/v2 comparison uses (tags variant:v1 / variant:v2 in neatlogs).
COMPARISON = {
    "plan": [("v1", "20261011T013638Z-plan-openllmetry", "20261011T013824Z-openllmetry-proposed"),
             ("v2", "20261011T013704Z-plan-openllmetry", "20261011T013847Z-openllmetry-proposed"),
             ("v1", "20261011T013725Z-plan-neatlogs", "20261011T013836Z-neatlogs-proposed"),
             ("v2", "20261011T013748Z-plan-neatlogs", "20261011T013900Z-neatlogs-proposed")],
    "plan_history": ["20261010T234842Z-plan-openllmetry", "20261010T235208Z-plan-neatlogs"],
    "fix": [("v1", "20261011T013927Z-fix-openinference"), ("v2", "20261011T014344Z-fix-openinference")],
    "fix_finding": "openinference-run_status-openai-agents-top-level-span-status-ok",
}
# Leads Trueup withdrew itself: its neatlogs adapter read the finish reason from one namespace only
# (hackathon.md, "Trueup's own false alarm"). Per scenario, from run 20261010T203332Z-neatlogs.
OWN_FALSE_ALARM = {"ag-bad-tool": 1, "ag-llm-fails": 1, "ag-max-turns": 3, "ag-run": 2, "ag-streamed": 2,
                   "ag-streamed-cut": 1, "ag-streamed-error": 1, "ag-tool-raises": 2, "lc-invoke": 1,
                   "lc-refusal": 1, "lc-stream": 1, "lg-agent": 2, "lg-llm-fails": 1, "lg-parallel": 2,
                   "lg-step-limit": 3, "lg-stream": 2, "lg-tool-raises": 1}


class VerifyFailed(Exception):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True, default=str) + "\n")


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


# Recomputing -----------------------------------------------------------------------------------

def _leads_of(truth: dict[str, Any], spans: list[dict[str, Any]], library: str) -> list[dict[str, Any]]:
    from trueup.core.compare import compare, leads
    from trueup.core.model import Observation

    obs = Observation.from_dict({"truth": truth, "trace": {"library": library, "versions": {}, "spans": spans}})
    return [m.to_dict() for m in leads(compare(obs))]


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(json.dumps(a.get(k), sort_keys=True) == json.dumps(b.get(k), sort_keys=True)
               for k in ("check", "field", "truth", "trace"))


def _of_finding(lead: dict[str, Any], f: dict[str, Any]) -> bool:
    return lead["check"] == f["check"] and grp.field_kind(lead["field"]) == f["field"]


def lead_key(lead: dict[str, Any], scenario: dict[str, Any]) -> list[str]:
    """The finding key a lead would group under: check, field, code path, trace shape."""
    return [lead["check"], grp.field_kind(lead["field"]), grp.code_path(scenario), grp.trace_shape(lead)]


def totals(leads: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    ls = [m for v in leads.values() for m in v]
    return {"scenarios": len(leads), "leads": len(ls), "high": sum(m["severity"] == "high" for m in ls),
            "medium": sum(m["severity"] == "medium" for m in ls)}


def cost(inp: int, out: int) -> float:
    return round((inp * PRICE["input"] + out * PRICE["output"]) / 1e6, 4)


def v1v2_table(v: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per variant and job, from the raw run data in v1v2.json."""
    rows = []
    key = {lib: {json.dumps(k) for k in ks} for lib, ks in v["answer_key"].items()}
    for variant in ("v1", "v2"):
        runs = [r for r in v["plan"] if r["variant"] == variant]
        props = [p for r in runs for p in r["proposals"]]
        hits = set()
        bad = 0
        for r in runs:
            for lead in r["leads"]:
                k = json.dumps(lead_key(lead, r["scenarios"][lead["scenario"]]))
                if k in key[r["library"]]:
                    hits.add((r["library"], k))
            bad += sum(1 for p in r["proposals"] if p["accepted"] and p.get("app_crashed"))
        size = sum(len(key[r["library"]]) for r in runs)
        rows.append({
            "job": "planner", "variant": variant, "runs": [r["run_id"] for r in runs],
            "first_try": f"{sum(p['revisions'] == 0 and p['accepted'] for p in props)} of {len(props)}",
            "accepted": f"{sum(p['accepted'] for p in props)} of {len(props)}",
            "tries_per_item": round(sum(p["tries"] for p in props) / len(props), 2),
            "calls": sum(r["usage"]["calls"] for r in runs),
            "json_retries": sum(r["usage"].get("json_retries", 0) for r in runs),
            "input_tokens": sum(r["usage"]["input_tokens"] for r in runs),
            "output_tokens": sum(r["usage"]["output_tokens"] for r in runs),
            "cost_usd": cost(sum(r["usage"]["input_tokens"] for r in runs),
                             sum(r["usage"]["output_tokens"] for r in runs)),
            "wall_s": round(sum(r["wall_s"] for r in runs), 1),
            "recall": f"{len(hits)} of {size}",
            "accepted_app_crash": bad,
            "traces_received": f"{sum(r['traces_received'] for r in runs)} of {sum(r['traces_opened'] for r in runs)}",
        })
    for variant in ("v1", "v2"):
        runs = [r for r in v["fix"] if r["variant"] == variant]
        rows.append({
            "job": "fixer", "variant": variant, "runs": [r["run_id"] for r in runs],
            "first_try": f"{sum(r['tries'][0]['ok'] for r in runs)} of {len(runs)}",
            "accepted": f"{sum(r['fixed'] for r in runs)} of {len(runs)}",
            "tries_per_item": round(sum(len(r["tries"]) for r in runs) / len(runs), 2),
            "calls": sum(r["usage"]["calls"] for r in runs),
            "json_retries": sum(r["usage"].get("json_retries", 0) for r in runs),
            "input_tokens": sum(r["usage"]["input_tokens"] for r in runs),
            "output_tokens": sum(r["usage"]["output_tokens"] for r in runs),
            "cost_usd": cost(sum(r["usage"]["input_tokens"] for r in runs),
                             sum(r["usage"]["output_tokens"] for r in runs)),
            "wall_s": round(sum(r["wall_s"] for r in runs), 1),
            "recall": f"{sum(r['fixed'] for r in runs)} of {len(runs)} fixed",
            "accepted_app_crash": 0,
            "traces_received": f"{sum(r['traces_received'] for r in runs)} of {sum(r['traces_opened'] for r in runs)}",
        })
    return rows


def headline(ev: Path) -> dict[str, Any]:
    """Every headline number, recomputed from the files in ev."""
    findings = [_load(d / "finding.json") for d in sorted((ev / "findings").iterdir())]
    by_lib: dict[str, dict[str, int]] = {}
    for f in findings:
        b = by_lib.setdefault(f["library"], {"findings": 0, "high": 0, "medium": 0, "low": 0})
        b["findings"] += 1
        b[f["severity"]] += 1
    w = _load(ev / "withdrawn.json")
    by_rule: dict[str, int] = {}
    for x in w["withdrawn"]:
        by_rule[x["rule"]] = by_rule.get(x["rule"], 0) + x.get("count", 1)
    fixes = {}
    for f in findings:
        p = ev / "findings" / f["id"] / "proof.json"
        if not p.exists():
            continue
        proof = _load(p)
        still = [s for s in f["scenarios"] if any(_of_finding(m, f) for m in proof["after"]["leads"].get(s, []))]
        new = [(s, m["check"], m["field"]) for s, ls in proof["after"]["leads"].items() for m in ls
               if not any(_same(m, o) for o in proof["before"]["leads"].get(s, []))]
        fixes[f["id"]] = {"before": totals(proof["before"]["leads"]), "after": totals(proof["after"]["leads"]),
                          "finding_scenarios_still_wrong": len(still), "new_mismatches": len(new),
                          "proven": not still and not new and not proof["after"]["not_run"]}
    return {
        "findings": {"total": len(findings), "by_library": dict(sorted(by_lib.items())),
                     "by_severity": {s: sum(f["severity"] == s for f in findings) for s in ("high", "medium", "low")}},
        "withdrawn_by_rule": dict(sorted(by_rule.items())),
        "disputed_groups": len(w["disputed"]),
        "already_known": sum(f["dedupe"]["status"] == "already known" for f in findings),
        "fixes": fixes,
        "fixes_proven": sum(x["proven"] for x in fixes.values()),
        "upstream_drafts": sum(bool(f.get("upstream")) for f in findings),
        "v1v2": v1v2_table(_load(ev / "v1v2.json")),
    }


def verify(ev: Path, out: Callable[[str], None] = print) -> dict[str, Any]:
    """Raise VerifyFailed with every problem found; return the recomputed headline when all is well."""
    problems: list[str] = []
    man_path = ev / "manifest.json"
    if not man_path.exists():
        raise VerifyFailed(f"no {man_path}")
    manifest = _load(man_path)["files"]
    present = {str(p.relative_to(ev)) for p in ev.rglob("*") if p.is_file()} - {"manifest.json"}
    for rel in sorted(set(manifest) - present):
        problems.append(f"missing: {rel}")
    for rel in sorted(present - set(manifest)):
        problems.append(f"not in the manifest: {rel}")
    for rel in sorted(set(manifest) & present):
        if sha256(ev / rel) != manifest[rel]:
            problems.append(f"sha256 differs: {rel}")
    out(f"sha256: {len(set(manifest) & present)} files checked, {len(problems)} problem(s)")
    if problems:
        raise VerifyFailed("\n".join(problems))
    witness = ev / "witness"
    if witness.is_dir():
        before, after = _load(witness / "before.json"), _load(witness / "after.json")
        kinds = ("plain_sync", "stream_sync", "tool_sync", "plain_async")
        if before["normal_calls"]["total"] != sum(before["normal_calls"][key] for key in kinds):
            problems.append("witness: normal-call total does not match its mix")
        if before["normal_calls"]["disagreements"] != 0:
            problems.append("witness: normal calls contain a disagreement")
        if after["targeted_before_marks"] != sum(1 for item in before["breaks"] if item.get("finding")):
            problems.append("witness: before mark count does not match break records")
        if after["targeted_after_marks"] != sum(item["disagree_marks_after"] for item in after["breaks"]):
            problems.append("witness: after mark count does not match break records")
        if round(before["spend_after_usd"] - before["spend_before_usd"], 7) != before["gate_spend_usd"]:
            problems.append("witness: gate spend does not recompute")
        out(f"witness: {before['normal_calls']['total']} normal calls, "
            f"{before['normal_calls']['disagreements']} disagreements, "
            f"{after['targeted_before_marks']} -> {after['targeted_after_marks']} targeted marks")
        if problems:
            raise VerifyFailed("\n".join(problems))
    n = 0
    for d in sorted((ev / "findings").iterdir()):
        f = _load(d / "finding.json")
        got = _leads_of(_load(d / "truth.json"), _load(d / "spans.json"), f["library"])
        if not any(_same(m, f["example"]) for m in got):
            problems.append(f"{f['id']}: the comparer does not find the lead in its saved truth and spans")
        n += 1
        p = d / "proof.json"
        if p.exists():
            proof = _load(p)
            for sid, obs in proof["after_observations"].items():
                after = _leads_of(obs["truth"], obs["trace"]["spans"], f["library"])
                if any(_of_finding(m, f) for m in after):
                    problems.append(f"{f['id']}: {sid} still shows the finding in its after-patch spans")
    out(f"comparer re-run: {n} findings")
    h = headline(ev)
    claimed = _load(ev / "headline.json")
    if json.loads(json.dumps(h)) != claimed:
        for k in sorted(set(h) | set(claimed)):
            if json.dumps(h.get(k), sort_keys=True) != json.dumps(claimed.get(k), sort_keys=True):
                problems.append(f"headline.json {k}: claimed {json.dumps(claimed.get(k))[:300]}, "
                                f"recomputed {json.dumps(h.get(k))[:300]}")
    if problems:
        raise VerifyFailed("\n".join(problems))
    return h


def print_headline(h: dict[str, Any], out: Callable[[str], None] = print) -> None:
    out(f"findings: {h['findings']['total']} ({', '.join(f'{k} {v}' for k, v in h['findings']['by_severity'].items())})")
    for lib, b in h["findings"]["by_library"].items():
        out(f"  {lib}: {b['findings']} (high {b['high']}, medium {b['medium']}, low {b['low']})")
    out(f"withdrawn by rule: {h['withdrawn_by_rule']}; disputed groups: {h['disputed_groups']}; "
        f"already known: {h['already_known']}")
    out(f"fixes proven: {h['fixes_proven']} of {len(h['fixes'])}")
    for fid, x in h["fixes"].items():
        b, a = x["before"], x["after"]
        out(f"  {fid}: leads {b['leads']} (high {b['high']}) -> {a['leads']} (high {a['high']}); "
            f"new mismatches {x['new_mismatches']}")
    out("v1/v2:")
    for r in h["v1v2"]:
        out(f"  {r['job']} {r['variant']}: first try {r['first_try']}, tries/item {r['tries_per_item']}, "
            f"calls {r['calls']} (JSON retries {r['json_retries']}), tokens {r['input_tokens']}/{r['output_tokens']}, "
            f"${r['cost_usd']}, {r['wall_s']} s, recall {r['recall']}")


# Building --------------------------------------------------------------------------------------

def trim_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for s in spans:
        attrs = {k: v for k, v in s.get("attributes", {}).items() if not DROP_ATTR.search(k)}
        events = [{"name": e.get("name"), "attributes": {k: (v[:200] if isinstance(v, str) else v)
                                                         for k, v in (e.get("attributes") or {}).items()
                                                         if k != "exception.stacktrace"}}
                  for e in s.get("events", [])]
        out.append({k: s[k] for k in ("name", "kind", "span_id", "parent_id", "start_ns", "end_ns", "status", "scope")
                    if k in s} | {"attributes": attrs, "events": events})
    return out


def trim_truth(t: dict[str, Any]) -> dict[str, Any]:
    return t  # the comparer reads most of the truth log, fake_log included; it is small


def _trimmed_observation(obs: dict[str, Any], library: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Trimmed truth and spans, if the comparer gives the same leads on them; else the originals."""
    full = _leads_of(obs["truth"], obs["trace"]["spans"], library)
    t, s = trim_truth(obs["truth"]), trim_spans(obs["trace"]["spans"])
    if json.dumps(_leads_of(t, s, library), sort_keys=True) == json.dumps(full, sort_keys=True):
        return t, s
    return obs["truth"], obs["trace"]["spans"]


def _merged_findings(runs: Path) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for f in sorted(runs.glob("*/findings.json")):
        d = _load(f)
        for x in d["findings"]:
            m = merged.get(x["id"])
            if m is None:
                merged[x["id"]] = {**x, "found_in": [d["run_id"]], "versions_run": d["run_id"]}
                continue
            m["found_in"].append(d["run_id"])
            for sid in x["details"]["scenarios"]:
                if sid not in m["details"]["scenarios"]:
                    m["details"]["scenarios"].append(sid)
            m["details"]["leads"] += x["details"]["leads"]
    return merged


def _run_of(runs: Path, merged: dict[str, Any], sid: str) -> Path:
    for r in merged["found_in"]:
        if (runs / r / f"{sid}.json").exists():
            return runs / r
    raise FileNotFoundError(f"no observation for {sid}")


def build(root: Path, out: Callable[[str], None] = print) -> Path:
    from trueup.scenarios import get as get_scenario

    runs, ev = root / ".trueup" / "runs", root / EVIDENCE
    # The open-PR matrix is generated by scripts/neatlogs_pr_matrix.py directly
    # in evidence/. Preserve it while rebuilding the rest of the bundle.
    neatlogs_pr_matrix = _load(ev / "neatlogs-pr-matrix.json") if (ev / "neatlogs-pr-matrix.json").exists() else None
    witness_evidence = ({p.name: p.read_bytes() for p in (ev / "witness").glob("*.json")}
                        if (ev / "witness").is_dir() else {})
    if ev.exists():
        shutil.rmtree(ev)
    (ev / "findings").mkdir(parents=True)
    if witness_evidence:
        (ev / "witness").mkdir()
        for name, data in witness_evidence.items():
            (ev / "witness" / name).write_bytes(data)
    business_plan = root / "docs" / "business-plan.md"
    if not business_plan.is_file():
        raise FileNotFoundError(f"missing cfo.ai business-plan artifact: {business_plan}")
    shutil.copy(business_plan, ev / "business-plan.md")
    neatlogs_evidence = root / ".trueup" / "neatlogs"
    if neatlogs_evidence.is_dir():
        shutil.copytree(neatlogs_evidence, ev / "neatlogs")
    entire_evidence = root / ".trueup" / "entire"
    if entire_evidence.is_dir():
        shutil.copytree(entire_evidence, ev / "entire")
    if neatlogs_pr_matrix is not None:
        _dump(ev / "neatlogs-pr-matrix.json", neatlogs_pr_matrix)
    merged = _merged_findings(runs)
    run_rows: dict[str, dict[str, Any]] = {}
    for fid, x in sorted(merged.items()):
        d = ev / "findings" / fid
        det = x["details"]
        sid = det["example"]["scenario"]
        rdir = _run_of(runs, x, sid)
        r = _load(rdir / f"{sid}.json")
        truth, spans = _trimmed_observation(r["observation"], x["library"])
        example = next(m for m in det["leads"] if m["scenario"] == sid and m["field"] == det["example"]["field"])
        up = root / "upstream" / fid
        dd = x.get("dedupe") or {}
        finding = {
            "id": fid, "title": x["title"], "library": x["library"], "severity": x["severity"],
            "check": det["check"], "field": det["field"], "code_path": det["code_path"], "trace": det["trace"],
            "scenarios": sorted(det["scenarios"]), "example": example, "rules": det["rules"],
            "leads": det["leads"], "found_in": x["found_in"], "example_run": rdir.name,
            "dedupe": {k: dd.get(k) for k in ("status", "links", "matched", "related", "searches")},
            "upstream": {"issue": f"upstream/{fid}/issue.md", "pr": f"upstream/{fid}/pr.md",
                         "status": "not yet posted"} if (up / "issue.md").exists() else None,
            "fixed": (root / "fixes" / fid / "proof.json").exists(),
        }
        _dump(d / "finding.json", finding)
        try:
            scenario = get_scenario(sid)
        except KeyError:
            from trueup.check import scenario_for_run

            scenario = scenario_for_run(root, sid, r["observation"])
        _dump(d / "scenario.json", scenario.to_dict())
        _dump(d / "truth.json", truth)
        _dump(d / "spans.json", spans)
        repro = up / "repro.py" if (up / "repro.py").exists() else rdir / "repros" / f"{x['library']}-{sid}.py"
        if repro.exists():
            shutil.copy(repro, d / "repro.py")
        fx = root / "fixes" / fid
        if (fx / "proof.json").exists():
            proof = _load(fx / "proof.json")
            # The after-patch truth and spans of the example scenario; the other scenarios are in the lead lists.
            o = proof["after_observations"][sid]
            t, sp = _trimmed_observation(o, x["library"])
            proof["after_observations"] = {sid: {"truth": t, "trace": {"spans": sp}}}
            _dump(d / "proof.json", proof)
            shutil.copy(fx / "patch.diff", d / "patch.diff")
            if (fx / "graph-compare.json").exists():
                shutil.copy(fx / "graph-compare.json", d / "graph.json")
        for rid in x["found_in"]:
            run_rows.setdefault(rid, {"run_id": rid, "kind": "sweep+check", "library": x["library"],
                                      "variant": None, "neatlogs_session": None,
                                      "versions": r["observation"]["trace"].get("versions", {})})
    _withdrawn(runs, ev)
    _v1v2(root, runs, ev, merged, run_rows)
    _dump(ev / "runs.json", sorted(run_rows.values(), key=lambda r: r["run_id"]))
    _dump(ev / "headline.json", {})  # placeholder so headline() can read the tree
    write_manifest(ev)
    h = headline(ev)
    _dump(ev / "headline.json", h)
    write_manifest(ev)
    out(f"wrote {ev}: {len(merged)} findings, {sum(1 for _ in ev.rglob('*') if _.is_file())} files, "
        f"{sum(p.stat().st_size for p in ev.rglob('*') if p.is_file()) // 1024} KB")
    return ev


def write_manifest(ev: Path) -> None:
    files = {str(p.relative_to(ev)): sha256(p) for p in sorted(ev.rglob("*")) if p.is_file()}
    files.pop("manifest.json", None)
    _dump(ev / "manifest.json", {"algorithm": "sha256", "files": files})


def _withdrawn(runs: Path, ev: Path) -> None:
    withdrawn, disputed = [], []
    for f in sorted(runs.glob("*/withdrawn.json")):
        for x in _load(f)["withdrawn"]:
            fail = next(r for r in x["rules"] if r["status"] == "fail")
            withdrawn.append({"run_id": _load(f)["run_id"], "scenario": x["lead"]["scenario"],
                              "library": x["lead"]["library"], "check": x["lead"]["check"],
                              "field": x["lead"]["field"], "truth": x["lead"]["truth"], "trace": x["lead"]["trace"],
                              "rule": fail["rule"], "reason": fail["reason"]})
    for f in sorted(runs.glob("*/findings.json")):
        for x in _load(f).get("disputed_semantics", []):
            disputed.append({"run_id": _load(f)["run_id"], "id": x["id"], "title": x["title"],
                             "scenarios": x["details"]["scenarios"], "reason": x["details"]["rules"].get("reference")})
    for sid, n in OWN_FALSE_ALARM.items():
        withdrawn.append({"run_id": "20261010T203332Z-neatlogs", "scenario": sid, "library": "neatlogs",
                          "check": "finish", "field": "finish reason", "count": n, "rule": "trueup_own_false_alarm",
                          "reason": "Trueup's neatlogs adapter read only neatlogs.llm.finish_reason; these framework "
                                    "spans carry it in llm.finish_reason. Adapter fixed; the leads were ours."})
    _dump(ev / "withdrawn.json", {"withdrawn": withdrawn, "disputed": disputed})


def _usage_of(run_dir: Path) -> dict[str, Any]:
    s = _load(run_dir / "spend.json")
    return {**s.get("usage", {}), "key_spend_delta_usd": s.get("run_cost_usd")}


def _received(root: Path, session: str) -> int:
    p = root / ".trueup" / "neatlogs-api" / "v1v2" / f"{session}.json"
    return _load(p)["totals"]["traces"] if p.exists() else 0


def _trace_links(root: Path, session: str) -> list[str]:
    p = root / ".trueup" / "neatlogs-api" / "v1v2" / f"{session}.json"
    if not p.exists():
        return []
    return [f"https://app.neatlogs.com/traces/{t['trace_id']}" for t in _load(p).get("traces", [])]


def _v1v2(root: Path, runs: Path, ev: Path, merged: dict[str, Any], run_rows: dict[str, Any]) -> None:
    answer = {}
    for x in merged.values():
        d = x["details"]
        answer.setdefault(x["library"], []).append([d["check"], d["field"], d["code_path"], d["trace"]])
    plans = []
    for variant, rid, sweep_id in COMPARISON["plan"]:
        p = _load(runs / rid / "plan.json")
        pdir = root / ".trueup" / "v1v2" / variant / "proposed" / p["library"]
        scen = {f.stem: _load(f) for f in sorted(pdir.glob("*.json"))}
        accepted = {a["id"]: a for a in p["accepted"]}
        sw = _load(runs / sweep_id / "leads.json")
        mine = {a["id"] for a in p["accepted"]}
        leads = [{**m, "scenario": s["scenario"]} for s in sw["scenarios"] if s["scenario"] in mine
                 for m in s["mismatches"] if m.get("kind", "lead") == "lead"]
        props = []
        for a in p["accepted"]:
            obs = _load(runs / sweep_id / f"{a['id']}.json")["observation"]["truth"]
            props.append({"id": a["id"], "accepted": True, "revisions": a["revisions"], "tries": a["revisions"] + 1,
                          "app_crashed": obs.get("exception") in ("AttributeError", "TypeError", "NameError")})
        props += [{"id": r["id"], "accepted": False, "revisions": r["tries"], "tries": r["tries"],
                   "reasons": r["reasons"]} for r in p["rejected"]]
        plans.append({"run_id": rid, "variant": variant, "library": p["library"], "sweep_run": sweep_id,
                      "usage": _usage_of(runs / rid), "wall_s": p["wall_s"], "proposals": props,
                      "scenarios": {k: {kk: v.get(kk) for kk in ("provider", "api", "framework", "app", "model")}
                                    for k, v in scen.items() if k in accepted},
                      "leads": leads, "traces_opened": len(p.get("traces_opened", [])),
                      "traces_received": _received(root, rid)})
        run_rows[rid] = {"run_id": rid, "kind": "plan", "library": p["library"], "variant": variant,
                         "neatlogs_session": rid, "neatlogs_trace_links": _trace_links(root, rid),
                         "versions": {"model": p["model"]}}
        run_rows[sweep_id] = {"run_id": sweep_id, "kind": "sweep (proposals)", "library": p["library"],
                              "variant": variant, "neatlogs_session": None, "versions": {}}
    history = []
    for rid in COMPARISON["plan_history"]:
        p = _load(runs / rid / "plan.json")
        history.append({"run_id": rid, "library": p["library"], "usage": _usage_of(runs / rid),
                        "first_try": sum(a["revisions"] == 0 for a in p["accepted"]), "proposals": len(p["proposals"]),
                        "note": "v1 before its prompt was corrected (exception required, real app descriptions)"})
    fixes = []
    for variant, rid in COMPARISON["fix"]:
        t = _load(root / ".trueup" / "v1v2" / variant / "fix" / "runs" / f"{rid}.json")
        fixes.append({"run_id": rid, "variant": variant, "finding": t["finding"], "fixed": t["fixed"],
                      "tries": [{"try": x["try"], "ok": x["ok"], "stage": x.get("stage"),
                                 "reason": (x.get("reason") or "")[:300]} for x in t["tries"]],
                      "usage": {**t["usage"], "key_spend_delta_usd": t["cost_usd"]}, "wall_s": t["wall_s"],
                      "traces_opened": len(t.get("traces_opened", [])), "traces_received": _received(root, rid)})
        run_rows[rid] = {"run_id": rid, "kind": "fix", "library": t["library"], "variant": variant,
                         "neatlogs_session": rid, "neatlogs_trace_links": _trace_links(root, rid),
                         "versions": {"model": t["model"], "clone_commit": t.get("commit")}}
    fix_history = []
    for f in sorted((root / "fixes" / COMPARISON["fix_finding"] / "runs").glob("*.json")):
        t = _load(f)
        fix_history.append({"run_id": t["run_id"], "fixed": t["fixed"], "tries": len(t["tries"]),
                            "calls": (t.get("usage") or {}).get("calls"),
                            "input_tokens": (t.get("usage") or {}).get("input_tokens")})
    _dump(ev / "v1v2.json", {"answer_key": answer, "plan": plans, "plan_history": history, "fix": fixes,
                             "fix_history": fix_history, "price_per_million": PRICE,
                             "note": "cost_usd = tokens at list price; key_spend_delta_usd = the proxy's spend "
                                     "before/after, which lags (hackathon.md)."})
