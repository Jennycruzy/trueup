"""trueup report: one static page, docs/index.html, built from evidence/ only.

Plain HTML and CSS: no scripts, no external files, light and dark by the reader's setting, readable at
phone width. The page is the same bytes for the same bundle (no dates or times in it).
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from trueup.demo import DEFAULT_FINDING
from trueup.evidence import REPO_URL, _load, headline

STORY = DEFAULT_FINDING

CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1b1b1b;--muted:#5c5c5c;--line:#d8d8d8;--soft:#f4f4f4;
--bad:#b3261e;--good:#1e6b34}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#e8e8e8;--muted:#a8a8a8;--line:#3a3a3a;
--soft:#1f1f1f;--bad:#ff8a80;--good:#7fd48f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:58rem;margin:0 auto;padding:1rem}h1{font-size:1.6rem;margin:.5rem 0}
h2{font-size:1.25rem;margin-top:2.2rem;border-bottom:1px solid var(--line);padding-bottom:.3rem}
h3{font-size:1.05rem;margin-top:1.4rem}a{color:inherit}p.muted,.muted{color:var(--muted)}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}table{border-collapse:collapse;width:100%;font-size:.92rem}
th,td{border:1px solid var(--line);padding:.35rem .5rem;text-align:left;vertical-align:top}
th{background:var(--soft)}code,pre{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.85rem}
pre{background:var(--soft);padding:.7rem;overflow-x:auto;border:1px solid var(--line)}
.bad{color:var(--bad);font-weight:600}.good{color:var(--good);font-weight:600}
ol.steps{padding-left:1.3rem}ol.steps>li{margin-bottom:1rem}
.flow{display:flex;flex-wrap:wrap;gap:.3rem;align-items:center;margin:.6rem 0}
.flow span{border:1px solid var(--line);padding:.15rem .5rem;background:var(--soft)}
details{margin:.5rem 0}summary{cursor:pointer}
"""


def _t(rows: list[list[Any]], head: list[str]) -> str:
    h = "".join(f"<th>{escape(x)}</th>" for x in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="wrap"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def _e(v: Any) -> str:
    return escape(v if isinstance(v, str) else json.dumps(v))


def _link(path: str, text: str | None = None) -> str:
    return f'<a href="{escape(REPO_URL)}/{escape(path)}">{escape(text or path)}</a>'


def _spans(spans: list[dict[str, Any]]) -> str:
    names = {s.get("span_id"): s["name"] for s in spans}
    rows = []
    for s in spans:
        code = s["status"]["code"]
        root = names.get(s.get("parent_id")) is None
        ev = ", ".join(e["name"] for e in s.get("events", [])) or "-"
        rows.append([escape(s["name"]), f"<b>{escape(code)}</b> (top level)" if root else escape(code),
                     escape(names.get(s.get("parent_id")) or "(root)"), escape(ev)])
    return _t(rows, ["span", "status", "parent", "events"])


def page(ev: Path) -> str:
    h = headline(ev)
    findings = [_load(d / "finding.json") for d in sorted((ev / "findings").iterdir())]
    w = _load(ev / "withdrawn.json")
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             "<title>Trueup evidence</title>", f"<style>{CSS}</style></head><body><main>",
             "<h1>Trueup evidence</h1>",
             "<p>Trueup runs AI agents against a fake provider, so it knows what really happened, and compares "
             "that with what the tracing library recorded. Every number on this page is recomputed from "
             f"{_link('evidence/', 'evidence/')} by <code>uv run trueup verify</code>, with no keys and no network.</p>"]

    # Headline ---------------------------------------------------------------------------------
    parts.append("<h2>Headline</h2>")
    rows = [[escape(lib), str(b["findings"]), str(b["high"]), str(b["medium"])]
            for lib, b in h["findings"]["by_library"].items()]
    rows.append(["<b>all</b>", f"<b>{h['findings']['total']}</b>", str(h["findings"]["by_severity"]["high"]),
                 str(h["findings"]["by_severity"]["medium"])])
    parts.append(_t(rows, ["library", "findings", "high", "medium"]))
    wd = ", ".join(f"{escape(k)}: {v}" for k, v in h["withdrawn_by_rule"].items())
    parts.append(f"<p>Withdrawn leads by rule: {wd}. Disputed groups (the conventions do not decide): "
                 f"{h['disputed_groups']}. Already reported upstream: {h['already_known']}. "
                 f"Fixes proven: {h['fixes_proven']} of {len(h['fixes'])}. Upstream drafts: "
                 f"{h['upstream_drafts']}, none posted.</p>")
    rows = [[_link(f"evidence/findings/{fid}/", fid), f"{x['before']['leads']} ({x['before']['high']} high)",
             f"{x['after']['leads']} ({x['after']['high']} high)", str(x["new_mismatches"]),
             '<span class="good">yes</span>' if x["proven"] else '<span class="bad">no</span>']
            for fid, x in h["fixes"].items()]
    parts.append("<h3>Fixes: leads in the full scenario library, before and after the patch</h3>")
    parts.append(_t(rows, ["finding", "before", "after", "new mismatches", "proven"]))
    parts.append("<h3>v1 and v2 of the planner and the fixer</h3>")
    rows = [[escape(r["job"]), escape(r["variant"]), escape(r["first_try"]), str(r["tries_per_item"]),
             f"{r['calls']} ({r['json_retries']})", f"{r['input_tokens']:,} / {r['output_tokens']:,}",
             f"${r['cost_usd']:.2f}", f"{r['wall_s']:.0f} s", escape(r["recall"]),
             escape(r["traces_received"])] for r in h["v1v2"]]
    parts.append(_t(rows, ["job", "version", "first try accepted", "tries per item", "model calls (JSON retries)",
                           "tokens in / out", "cost (list price)", "wall time", "answer-key recall",
                           "traces found in neatlogs"]))
    parts.append("<p class=muted>One run per library and version, so these are small samples. Run ids, "
                 "neatlogs session ids and the raw data are in "
                 f"{_link('evidence/v1v2.json')}.</p>")

    # One finding, start to finish -------------------------------------------------------------
    f = next(x for x in findings if x["id"] == STORY)
    d = ev / "findings" / STORY
    truth, spans = _load(d / "truth.json"), _load(d / "spans.json")
    proof = _load(d / "proof.json")
    sid = f["example"]["scenario"]
    after = proof["after_observations"][sid]
    parts.append("<h2>One finding, start to finish</h2>")
    parts.append('<div class="flow"><span>shown as OK</span>→<span>found</span>→<span>double-checked</span>→'
                 "<span>fixed</span>→<span>proven</span></div>")
    parts.append(f"<p><b>{escape(f['title'])}</b> ({escape(f['severity'])}). Example scenario "
                 f"<code>{escape(sid)}</code>: {escape(_load(d / 'scenario.json')['does'])}</p>")
    rules = "".join(f"<li><code>{escape(k)}</code>: {escape(v)}</li>" for k, v in f["rules"].items())
    history = "; ".join(f"{t['run_id']}: {t['tries']} tries, {'fixed' if t['fixed'] else 'not fixed'}"
                        for t in _load(ev / "v1v2.json")["fix_history"])
    parts.append("<ol class=steps>")
    parts.append(f"<li><b>Shown as OK.</b> What really happened: {escape(str(truth['calls']))} provider "
                 f"call(s), the app raised <code>{escape(str(truth.get('exception')))}</code>. What OpenInference "
                 f"exported:{_spans(spans)}</li>")
    parts.append(f"<li><b>Found.</b> The comparer's lead: {escape(f['example']['field'])}: truth "
                 f"<span class=good>{_e(f['example']['truth'])}</span>, trace <span class=bad>"
                 f"{_e(f['example']['trace'])}</span>. Same lead in {len(f['scenarios'])} scenarios: "
                 f"{escape(', '.join(f['scenarios']))}.</li>")
    parts.append(f"<li><b>Double-checked.</b> Every rule passed:<ul>{rules}</ul>Searched the library's issues "
                 f"and PRs: {escape(f['dedupe']['status'])}.</li>")
    parts.append(f"<li><b>Fixed.</b> The model drafted a patch and a test; code kept it only after the test "
                 f"failed before and passed after, the package's suite showed no new failure and every scenario "
                 f"matched truth. Earlier fix runs on this finding: "
                 f"{escape(history)}."
                 f"<details><summary>patch.diff</summary><pre>{escape((d / 'patch.diff').read_text())}</pre>"
                 "</details></li>")
    rows = [[escape(r["scenario"]), _e(r["truth"]), f'<span class=bad>{_e(r["before"])}</span>',
             f'<span class=good>{_e(r["after"])}</span>'] for r in proof["rows"]]
    fx = h["fixes"][STORY]
    parts.append(f"<li><b>Proven.</b> The patch applied to the library's main branch (commit "
                 f"<code>{escape(proof['commit'][:10])}</code>), the full scenario library run again:"
                 f"{_t(rows, ['scenario', 'truth', 'before', 'after'])}"
                 f"<p>All scenarios: {fx['before']['leads']} leads ({fx['before']['high']} high) before, "
                 f"{fx['after']['leads']} ({fx['after']['high']} high) after, {fx['new_mismatches']} new. "
                 f"The same run after the patch:</p>{_spans(after['trace']['spans'])}</li>")
    parts.append("</ol>")

    # All findings ------------------------------------------------------------------------------
    parts.append("<h2>All findings</h2>")
    order = {"high": 0, "medium": 1, "low": 2}
    rows = []
    for x in sorted(findings, key=lambda x: (x["library"], order[x["severity"]], x["id"])):
        known = x["dedupe"]["status"]
        if x["dedupe"].get("links"):
            known += " " + " ".join(f'<a href="{escape(u)}">{escape(u.rsplit("/", 2)[-2] + " " + u.rsplit("/", 1)[-1])}</a>'
                                   for u in x["dedupe"]["links"])
        rows.append([escape(x["library"]), escape(x["severity"]),
                     _link(f"evidence/findings/{x['id']}/", x["title"]),
                     f"{escape(x['example']['field'])}: truth {_e(x['example']['truth'])}, trace "
                     f"{_e(x['example']['trace'])}", str(len(x["scenarios"])), known,
                     "yes, proven" if x["fixed"] else "-"])
    parts.append(_t(rows, ["library", "severity", "finding", "example", "scenarios", "known upstream", "fixed"]))

    # Withdrawn -------------------------------------------------------------------------------
    parts.append("<h2>Withdrawn leads</h2><p>A lead is withdrawn when a rule fails. Withdrawn leads are kept "
                 "and counted.</p>")
    rows = [[escape(x["library"]), escape(x["scenario"]), escape(x["check"]), str(x.get("count", 1)),
             escape(x["rule"]), escape(x["reason"])] for x in w["withdrawn"]]
    parts.append(_t(rows, ["library", "scenario", "check", "leads", "rule", "reason"]))
    parts.append("<h3>Disputed: the conventions do not decide</h3>")
    rows = [[escape(x["title"]), escape(", ".join(x["scenarios"])), escape(x["reason"] or "")] for x in w["disputed"]]
    parts.append(_t(rows, ["group", "scenarios", "why"]))

    # Upstream drafts ---------------------------------------------------------------------------
    parts.append("<h2>Upstream drafts</h2><p><b>Not yet posted.</b> Issue and PR text for each fixed finding, "
                 "with a standalone repro run on the latest release and on the patched code.</p><ul>")
    for x in findings:
        if x.get("upstream"):
            parts.append(f"<li>{escape(x['title'])}: {_link(x['upstream']['issue'], 'issue draft')}, "
                         f"{_link(x['upstream']['pr'], 'PR draft')} <b>(not yet posted)</b></li>")
    parts.append("</ul>")
    parts.append("<h2>Check it yourself</h2><pre>git clone https://github.com/Jennycruzy/trueup && cd trueup\n"
                 "uv sync\nuv run pytest -q\nuv run trueup verify\n"
                 "uv run trueup sweep openllmetry --case ag-run</pre>"
                 "<p class=muted>verify fails if any byte of the bundle changed. The sweep needs no keys: the "
                 "provider is a local fake.</p></main></body></html>")
    return "\n".join(parts) + "\n"


def write(ev: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(ev))
    return out
