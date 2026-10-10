"""Search a library's GitHub issues and PRs (all states) for each finding. Read only.

Uses `gh search issues --include-prs`. Never opens, comments on or posts anything.
For each finding it records the searches with their dates, the titles of the
integration's issues and PRs, and whether one of them already covers the
finding ("already known", with the link).

Queries and matching are pure (queries, matches); gh_search is the only effect.
A match needs the integration's name and the specific behaviour in the title, so
it errs on the side of "not found"; the recorded searches let a reader check.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable

from trueup.core.model import Finding

REPOS = {"neatlogs": "neatlogs/neatlogs", "openinference": "Arize-ai/openinference",
         "openllmetry": "traceloop/openllmetry"}
FIELDS = "number,title,url,state,isPullRequest,createdAt"
PAUSE_S = 2.5  # GitHub allows 30 search requests a minute

# Integration names per code path (for search terms and title matching).
INTEGRATION = {
    "openai chat create": ("openai",), "openai chat stream": ("openai",),
    "openai responses create": ("responses",), "openai responses stream": ("responses",),
    "anthropic messages create": ("anthropic",), "anthropic messages stream": ("anthropic",),
    "langchain": ("langchain",), "langgraph": ("langgraph", "langchain"),
    "openai-agents": ("openai-agents", "openai agents", "agents sdk", "openai_agents"),
}
# Search words, and title phrases any of which counts as the same behaviour, per check.
BEHAVIOUR: dict[str, tuple[str, tuple[str, ...]]] = {
    "run_status": ("span status error", ("span status", "error status", "status error", "status to error", "status ok", "marked as error",
                                         "set_status")),
    "call_status": ("exception event", ("exception event", "record_exception", "record exception", "span status",
                                         "error status")),
    "span_closed": ("span not ended stream", ("not ended", "never ended", "not closed", "missing span", "no span",
                                              "span leak", "not exported", "unfinished")),
    "call_count": ("duplicate spans", ("duplicate", "double", "twice")),
    "tokens": ("token usage", ("token", "usage")),
    "finish": ("finish reason", ("finish reason", "finish_reason", "stop reason", "stop_reason")),
    "output": ("output", ("output", "refusal", "tool call", "function call", "tool_calls")),
    "error_recorded": ("error not recorded", ("error",)),
    "tools": ("tool span", ("tool",)),
}

# Title matches read by hand that do not cover the finding they matched: (finding id, url) -> why.
# They are kept as "related", not "already known".
REVIEWED_NOT_COVERING: dict[tuple[str, str], str] = {
    ("openinference-output-openai-chat-create-output-text-missing",
     "https://github.com/Arize-ai/openinference/pull/3996"):
        "fixes streamed refusal fragments being overwritten; the finding is a non-streamed refusal not recorded",
}


def queries(f: Finding) -> list[str]:
    path, check, field = f.details["code_path"], f.details["check"], f.details["field"]
    integ = INTEGRATION.get(path, (path,))[0]
    words = BEHAVIOUR.get(check, (check, ()))[0]
    if check == "output":
        words = "refusal" if "text" in field and _is_refusal(f) else ("tool calls" if "tool" in field else "output")
    stream = " stream" if path.endswith("stream") and "stream" not in words else ""
    return [f"{integ} {words}{stream}", words + stream]


def _is_refusal(f: Finding) -> bool:
    return any("refusal" in lead["scenario"] for lead in f.details.get("leads", []))


def matches(f: Finding, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Issues/PRs whose title names the integration and the behaviour."""
    path, check = f.details["code_path"], f.details["check"]
    integ = INTEGRATION.get(path, (path,))
    phrases = BEHAVIOUR.get(check, ("", (check,)))[1]
    if check == "output":
        phrases = ("refusal",) if _is_refusal(f) else (("tool call", "function call", "tool_calls")
                                                     if "tool" in f.details["field"] else ("output",))
    out = []
    for it in items:
        t = it.get("title", "").lower()
        if any(i in t for i in integ) and any(p in t for p in phrases):
            out.append(it)
    return out


def gh_search(args: list[str]) -> str:
    p = subprocess.run(["gh", "search", "issues", *args], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[-300:])
    return p.stdout


def _search(search: Callable[[list[str]], str], repo: str, query: str, limit: int,
            cache: dict[str, Any]) -> dict[str, Any]:
    if query in cache:
        return cache[query]
    rec: dict[str, Any] = {"repo": repo, "query": query, "states": "all", "include_prs": True,
                           "date": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        rec["results"] = json.loads(search([query, "--repo", repo, "--include-prs", "--limit", str(limit),
                                            "--json", FIELDS]))
    except (RuntimeError, ValueError, subprocess.TimeoutExpired, OSError) as e:
        rec["results"], rec["error"] = [], str(e)
    if search is gh_search:
        time.sleep(PAUSE_S)
    cache[query] = rec
    return rec


def dedupe(library: str, findings: list[Finding], search: Callable[[list[str]], str] = gh_search,
           ) -> dict[str, dict[str, Any]]:
    repo = REPOS[library]
    cache: dict[str, Any] = {}
    out = {}
    for f in findings:
        searches = [_search(search, repo, q, 30, cache) for q in queries(f)]
        integ = INTEGRATION.get(f.details["code_path"], (f.details["code_path"],))[0]
        listing = _search(search, repo, integ, 100, cache)
        seen: dict[str, dict[str, Any]] = {}
        for s in [*searches, listing]:
            for it in s["results"]:
                seen.setdefault(it["url"], it)
        found = matches(f, list(seen.values()))
        related = [{"title": h["title"], "url": h["url"], "why_not": REVIEWED_NOT_COVERING[(f.id, h["url"])]}
                   for h in found if (f.id, h["url"]) in REVIEWED_NOT_COVERING]
        hits = [h for h in found if (f.id, h["url"]) not in REVIEWED_NOT_COVERING]
        out[f.id] = {
            "status": "already known" if hits else "not found",
            "links": [h["url"] for h in hits],
            "matched": [{"title": h["title"], "url": h["url"], "state": h["state"]} for h in hits],
            "related": related,
            "searches": [{k: v for k, v in s.items() if k != "results"} | {"hits": len(s["results"])}
                         for s in searches],
            "integration_titles": {"query": integ, "date": listing["date"],
                                   "titles": [f"#{it['number']} {it['title']} ({it['state']})"
                                              for it in listing["results"]]},
            "errors": [s["error"] for s in [*searches, listing] if s.get("error")],
        }
    return out
