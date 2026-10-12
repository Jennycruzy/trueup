"""Build live/static/fixes.html from fixes/*/provenance.json, summary.md and suites.json.

Run: python live/build_fixes.py
The page shares its head, nav and footer with live/static/index.html. Plain titles live in PLAIN below;
every number (tries, tests, mismatches, cost, upstream link, Entire record) is read from the fix's files.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
OUT = STATIC / "fixes.html"

# finding id -> (library, what was wrong, before, after)
PLAIN = {
    "openinference-run_status-openai-agents-top-level-span-status-ok": (
        "Arize OpenInference", "A failed OpenAI Agents run was recorded as OK.",
        "The top step of the run said OK although the run had crashed.",
        "The top step says ERROR when the run fails. A tool error the agent recovers from still says OK."),
    "openllmetry-call_count-openai-agents-llm-spans-wrong": (
        "Traceloop OpenLLMetry", "Every OpenAI Agents AI call was recorded twice.",
        "A run that made 2 AI calls showed 4.",
        "The record shows one step for each real AI call."),
    "neatlogs-run_status-anthropic-messages-stream-top-level-span-status-ok": (
        "neatlogs", "A cut or failed Claude reply was recorded as OK.",
        "When the reply stream broke off, the AI step still ended OK.",
        "The AI step ends ERROR, with the error attached."),
    "neatlogs-run_status-openai-responses-stream-top-level-span-status-unset": (
        "neatlogs", "An OpenAI reply that sent an error halfway was left unmarked.",
        "The AI step had no status at all (UNSET), though the app raised an error.",
        "The AI step ends ERROR."),
    "neatlogs-output-openai-chat-create-output-text-missing": (
        "neatlogs", "When the AI refused to answer, the reply was recorded as empty.",
        "The reply text was empty.",
        "The refusal text is recorded as the reply."),
    "neatlogs-run_status-openai-agents-top-level-span-status-ok": (
        "neatlogs", "A failed OpenAI Agents run was recorded as OK.", "", ""),
}

# Sent by hand from upstream/neatlogs-openai-agents-processor-run-status/ (issue.md, pr.md); no fixes/ folder.
NEATLOGS_207 = {
    "library": "neatlogs",
    "title": "neatlogs' own OpenAI Agents recorder recorded a failed run as OK.",
    "before": "The workflow step, the top line in the dashboard, ended OK although the run raised an error.",
    "after": "The workflow step ends ERROR with the error message. Errors the run recovers from still say OK.",
    "facts": ["6 new tests: 2 fail without the fix, all 6 pass with it.",
              "neatlogs' unit tests: 534 passed; the 5 that fail, fail with and without the fix (optional "
              "packages not installed)."],
    "url": "https://github.com/neatlogs/neatlogs/pull/207",
    "label": "neatlogs/neatlogs#207",
}

FIELDS = {"top-level span status": "Run status", "LLM spans": "AI calls recorded", "output text": "Reply text"}


def _e(s: object) -> str:
    return html.escape(str(s), quote=True)


# Plain names for the practice failures shown on the page (the ids are internal test names).
PLAIN_FAILURES = {
    "ag-bad-tool": "Agent: the AI asks for a tool that does not exist",
    "ag-llm-fails": "Agent: the AI server fails on the second call",
    "ag-max-turns": "Agent: stopped after too many turns",
    "ag-run": "Agent: a normal run with one tool call",
    "ag-streamed-cut": "Agent: the connection drops mid-reply",
    "ag-streamed-error": "Agent: an error arrives mid-reply",
    "ag-tool-raises": "Agent: a tool fails and the agent recovers",
    "p-an-stream-helper-cut": "Claude: the connection drops mid-reply",
    "p-an-stream-helper-error-event": "Claude: an error arrives mid-reply",
    "oa-resp-stream-error-event": "OpenAI: an error arrives mid-reply",
}


def _rows(summary: str) -> list[dict]:
    """The finding's before/after table: one row per practice failure."""
    m = re.search(r"\| scenario \| field \| truth \| before \| after \|\n\|[-|]+\|\n((?:\|.*\|\n?)+)", summary)
    if not m:
        return []
    rows = []
    for line in m.group(1).strip().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            continue
        name, field, truth, before, after = cells
        truth = re.sub(r"ERROR \(app raised (\w+)\)", r"ERROR (\1)", truth).replace(" (provider requests)", "")
        rows.append({"name": name, "field": FIELDS.get(field, field), "truth": truth, "before": before,
                     "after": "matches" if after == "matches truth" else after})
    return rows


def _suites(fix: Path, library: str) -> list[str]:
    try:
        data = json.loads((fix / "suites.json").read_text())
    except (OSError, ValueError):
        return []
    after = [v for v in data.get("after", {}).values() if v]
    last = after[-1] if after else {}
    out = []
    for pkg, b in data.get("before", {}).items():
        a = last.get(pkg)
        if not a:
            continue
        name = library if pkg == "." else re.sub(r"^\w+-instrumentation-", "", pkg.rsplit("/", 1)[-1]) + " package"
        same = "no new failures" if a.get("failed", 0) <= b.get("failed", 0) else "new failures"
        out.append(f"{name} test suite: {b.get('passed')} passed before, {a.get('passed')} after, {same}.")
    return out


def _fix(fix: Path) -> dict | None:
    fid = fix.name
    summary_path = fix / "summary.md"
    if fid not in PLAIN or not summary_path.is_file():
        return None
    summary = summary_path.read_text()
    library, title, before, after = PLAIN[fid]
    fixed = "Result: fixed" in summary
    card = {"library": library, "title": title, "before": before, "after": after, "fixed": fixed,
            "rows": [r for r in _rows(summary) if r["before"] != "matches truth"], "facts": []}
    try:
        prov = json.loads((fix / "provenance.json").read_text())
    except (OSError, ValueError):
        prov = {}
    if not fixed:
        tries = len(re.findall(r"^\d+\. FAIL", summary, re.M))
        card["facts"] = ["The same bug in neatlogs' own Agents recorder is fixed in neatlogs #207.",
                         f"{tries} tries by Trueup here; none passed the proof step, so no fix is offered. "
                         "The failed tries are kept in the repo."]
        card["state"] = "not fixed"
        return card
    tests = sorted(p.name for p in fix.glob("test_*.py"))
    if tests:
        card["facts"].append("New test: fails before the fix, passes after.")
    card["facts"] += _suites(fix, library)
    proof = prov.get("proof") or {}
    if proof:
        card["facts"].append(f"All 57 practice failures re-run: {proof['leads_before']} wrong readings before, "
                             f"{proof['leads_after']} after, {proof['new_mismatches']} new.")
    tries = prov.get("tries") or {}
    if tries:
        failed = len(tries.get("failed", []))
        note = f", {failed} failed {'try' if failed == 1 else 'tries'} kept" if failed else ""
        card["facts"].append(f"{tries['count']} {'try' if tries['count'] == 1 else 'tries'}{note}; "
                             f"AI cost ${tries['cost_usd']:.2f}.")
    up = prov.get("upstream") or {}
    if up.get("posted") and up.get("url"):
        card["url"] = up["url"]
        m = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", up["url"])
        card["label"] = f"{m.group(1)}#{m.group(2)}" if m else up["url"]
    card["state"] = "sent" if card.get("url") else "ready"
    commit = prov.get("commit") or {}
    if commit.get("checkpoint") and commit.get("entire_url"):
        card["entire"] = commit["entire_url"]
    return card


def _card(c: dict) -> str:
    tag = {"sent": '<span class="tag ok">Sent</span>', "ready": '<span class="tag wait">Ready to send</span>',
           "not fixed": '<span class="tag bad">Not fixed</span>'}[c["state"]]
    out = [f'<article class="panel fix lift"><div class="head"><span class="tag">{_e(c["library"])}</span>{tag}</div>',
           f'<h3>{_e(c["title"])}</h3>']
    if c.get("before"):
        out.append('<div class="row-vs"><div><div class="k">Before</div><p class="muted" style="margin:4px 0 0">'
                   f'{_e(c["before"])}</p></div><div><div class="k">After</div><p class="muted" style="margin:4px 0 0">'
                   f'{_e(c["after"])}</p></div></div>')
    if c.get("rows") and c["state"] != "not fixed":
        body = "".join(f'<tr><td>{_e(PLAIN_FAILURES.get(r["name"], r["name"]))}</td><td class="r">{_e(r["before"])}</td>'
                       f'<td>{_e(r["truth"])}</td><td class="g" style="white-space:nowrap">'
                       f'{_e(r["after"])}</td></tr>' for r in c["rows"])
        out.append(f'<div class="tablewrap"><table><thead><tr><th>Practice failure</th><th>Recorded</th>'
                   f'<th>Really</th><th>After</th></tr></thead><tbody>{body}</tbody></table></div>')
    cls = ' class="no"' if c["state"] == "not fixed" else ""
    out.append('<ul class="facts">' + "".join(f"<li{cls}>{_e(f)}</li>" for f in c["facts"]) + "</ul>")
    links = []
    if c.get("url"):
        links.append(f'<a href="{_e(c["url"])}" target="_blank" rel="noopener">{_e(c["label"])} →</a>')
    elif c["state"] == "ready":
        links.append('<span class="muted">Ready to send: the issue and pull request are written.</span>')
    if c.get("entire"):
        links.append(f'<span class="muted">How this fix was made: <a href="{_e(c["entire"])}" target="_blank" '
                     'rel="noopener">Entire record →</a></span>')
    if links:
        out.append('<div class="links">' + "".join(links) + "</div>")
    out.append("</article>")
    return "".join(out)


def build() -> str:
    cards = [c for c in (_fix(p) for p in sorted((REPO / "fixes").iterdir()) if p.is_dir()) if c]
    sent = dict(NEATLOGS_207, state="sent", fixed=True, rows=[])
    cards.append(sent)
    order = {"sent": 0, "ready": 1, "not fixed": 2}
    cards.sort(key=lambda c: (order[c["state"]], c["library"] != "Arize OpenInference"))
    done = [c for c in cards if c["state"] != "not fixed"]
    tried = [c for c in cards if c["state"] == "not fixed"]
    n_sent = sum(c["state"] == "sent" for c in cards)

    index = (STATIC / "index.html").read_text()
    head = index[:index.index('<body class="site">')]
    head = re.sub(r"<title>.*?</title>", "<title>Fixes · Trueup</title>", head)
    head = re.sub(r'<meta name="description" content="[^"]*">',
                  '<meta name="description" content="Every fix Trueup wrote for tracing code, with its tests and '
                  'where it was sent.">', head)
    nav = index[index.index("<!-- nav -->"):index.index("<!-- /nav -->") + len("<!-- /nav -->")]
    foot = index[index.index("<!-- footer -->"):]
    main = f"""<main>
<section class="page-hero container">
  <p class="eyebrow">Fixes</p>
  <h1 style="font-size:clamp(2.2rem,6vw,4.4rem)">Every fix, with its proof.</h1>
  <p class="sub intro">Each fix repairs tracing code that wrote a wrong record. Each one comes with a new test that fails
  before and passes after, and the library's own tests still pass. <b>{len(done)} fixes</b>, <b>{n_sent} sent</b> to
  the companies that make these tools, the rest ready to send. Sent fixes are proposals until the maintainers merge them.</p>
</section>
<section class="container reveal" style="padding-top:24px">
  <div class="grid2">{"".join(_card(c) for c in done)}</div>
</section>
"""
    if tried:
        main += f"""<section class="container section reveal">
  <p class="eyebrow">Tried, not fixed</p>
  <h2>When a fix fails, we say so.</h2>
  <p class="intro">A try only counts if it passes the proof step. These did not, so no fix is offered.</p>
  <div class="grid2">{"".join(_card(c) for c in tried)}</div>
</section>
"""
    main += """<section class="container reveal">
  <div class="cta-band">
    <h2>See a fix switch the light off.</h2>
    <p>The live demo runs the tracing code as released, or with these fixes. Crash the bot both ways.</p>
    <div class="cta">
      <a class="btn btn-primary" href="/demo">Try the live demo <span aria-hidden="true">→</span></a>
      <a class="btn btn-ghost" href="https://github.com/Jennycruzy/trueup" target="_blank" rel="noopener">View on GitHub</a>
    </div>
  </div>
</section>
</main>
"""
    return head + '<body class="site">\n' + nav + "\n\n" + main + "\n" + foot


def main() -> None:
    OUT.write_text(build())
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
