"""Write fixes/<id>/PROVENANCE.md and provenance.json: how each fix was made.

Reads git history (the commit that first added the patch and its Entire-Checkpoint trailer), the
fixer's tries, the verifier's proof and the upstream link. Never invents an Entire record.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

ENTIRE_COMMIT_URL = "https://entire.io/gh/Jennycruzy/trueup/commit/{sha}"
NO_RECORD = "no Entire record for this commit"

# Pull requests that were really posted, by fix id. Everything else is a draft in upstream/<id>/.
POSTED = {
    "openinference-run_status-openai-agents-top-level-span-status-ok":
        "https://github.com/Arize-ai/openinference/pull/4024",
    "openllmetry-call_count-openai-agents-llm-spans-wrong":
        "https://github.com/traceloop/openllmetry/pull/4610",
    "neatlogs-run_status-openai-agents-top-level-span-status-ok":
        "https://github.com/neatlogs/neatlogs/pull/207",
}

_PRIVATE_PATH = re.compile(r"(?:/root|/home/[^/\s'\"]+)(?:/[^\s'\"),:]*)?")
_KEYS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bBearer\s+\S+", re.I),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token)(\s*[:=]\s*)\S+"),
]


def scrub(text: str) -> str:
    """Remove private paths and anything that looks like a key."""
    text = _PRIVATE_PATH.sub("<private path>", text)
    for pat in _KEYS:
        text = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}<hidden>" if m.re.groups == 2 else "<hidden>", text)
    return text


def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return r.stdout.strip() if r.returncode == 0 else ""


def commit_info(root: Path, rel_path: str) -> dict[str, Any] | None:
    shas = _git(root, "log", "--diff-filter=A", "--format=%H", "--", rel_path).split()
    if not shas:
        return None
    sha = shas[-1]
    date = _git(root, "log", "-1", "--format=%ad", "--date=short", sha)
    subject = _git(root, "log", "-1", "--format=%s", sha)
    trailer = _git(root, "log", "-1", "--format=%(trailers:key=Entire-Checkpoint,valueonly)", sha)
    checkpoint = trailer.splitlines()[0].strip() if trailer else None
    return {"sha": sha, "date": date, "subject": subject, "checkpoint": checkpoint,
            "entire_url": ENTIRE_COMMIT_URL.format(sha=sha) if checkpoint else None}


def explain(root: Path, checkpoint: str, lines: int = 15) -> list[str]:
    """First lines of Entire's read-only checkpoint summary, or [] when it is not available."""
    try:
        r = subprocess.run(["entire", "checkpoint", "explain", "--short", checkpoint], cwd=root,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []
    out = [scrub(x.rstrip()) for x in r.stdout.splitlines() if "Not generated yet" not in x]
    out = out[:lines]
    while out and (not out[-1].strip() or out[-1].startswith("#")):
        out.pop()
    return out


def _one_line(text: Any, limit: int = 200) -> str:
    s = " ".join(str(text or "").strip().split("\n")[0].split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


def tries_info(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    tries = d.get("tries") or []
    return {
        "count": len(tries),
        "failed": [{"try": t.get("try"), "reason": scrub(_one_line(t.get("reason")))}
                   for t in tries if not t.get("ok")],
        "model": d.get("model"),
        "cost_usd": d.get("cost_usd"),
    }


def proof_info(path: Path) -> dict[str, Any]:
    p = json.loads(path.read_text())
    total = lambda side: sum(len(v) for v in (p.get(side, {}).get("leads") or {}).values())  # noqa: E731
    return {"leads_before": total("before"), "leads_after": total("after"),
            "new_mismatches": len(p.get("new_mismatches") or [])}


def upstream_info(root: Path, fid: str) -> dict[str, Any] | None:
    if fid in POSTED:
        return {"posted": True, "url": POSTED[fid]}
    if (root / "upstream" / fid).is_dir():
        return {"posted": False, "path": f"upstream/{fid}/"}
    return None


def build(root: Path, fid: str, explain_cache: dict[str, list[str]] | None = None) -> dict[str, Any]:
    fx = root / "fixes" / fid
    commit = commit_info(root, f"fixes/{fid}/patch.diff")
    session: list[str] = []
    if commit and commit["checkpoint"]:
        cache = explain_cache if explain_cache is not None else {}
        if commit["checkpoint"] not in cache:
            cache[commit["checkpoint"]] = explain(root, commit["checkpoint"])
        session = cache[commit["checkpoint"]]
    return {"finding": fid, "commit": commit, "session_summary": session,
            "tries": tries_info(fx / "tries.json"), "proof": proof_info(fx / "proof.json"),
            "upstream": upstream_info(root, fid)}


def render(p: dict[str, Any]) -> str:
    out = [f"# How this fix was made: {p['finding']}", ""]
    c = p["commit"]
    out += ["## Commit", ""]
    if not c:
        out.append("The patch is not committed yet.")
    else:
        out.append(f"First added in `{c['sha'][:7]}` on {c['date']}: {c['subject']}")
        out.append("")
        if c["checkpoint"]:
            out.append(f"Entire record: checkpoint `{c['checkpoint']}`, [{c['entire_url']}]({c['entire_url']})")
        else:
            out.append(f"{NO_RECORD[0].upper()}{NO_RECORD[1:]}.")
    if p["session_summary"]:
        out += ["", "## What the session did", "", "```", *p["session_summary"], "```"]
    t = p["tries"]
    out += ["", "## Fixer tries", ""]
    if not t:
        out.append("No tries recorded.")
    else:
        out.append(f"{t['count']} {'try' if t['count'] == 1 else 'tries'}; {len(t['failed'])} failed.")
        for f in t["failed"]:
            out.append(f"- Try {f['try']} failed: {f['reason']}")
        if t["model"]:
            out.append(f"- Model: {t['model']}")
        if t["cost_usd"] is not None:
            out.append(f"- Cost: ${t['cost_usd']:.2f}")
    pr = p["proof"]
    out += ["", "## Verifier", "",
            f"Leads across all scenarios: {pr['leads_before']} before, {pr['leads_after']} after. "
            f"New mismatches: {pr['new_mismatches']}."]
    u = p["upstream"]
    out += ["", "## Upstream", ""]
    if not u:
        out.append("None.")
    elif u["posted"]:
        out.append(f"Posted: {u['url']}")
    else:
        out.append(f"Draft, not posted: [{u['path']}](../../{u['path']})")
    return scrub("\n".join(out)) + "\n"


def fix_ids(root: Path) -> list[str]:
    return sorted(d.name for d in (root / "fixes").iterdir() if (d / "proof.json").exists())


def write_all(root: Path, only: str | None = None) -> list[dict[str, Any]]:
    ids = fix_ids(root)
    if only is not None:
        if only not in ids:
            raise ValueError(f"no fixes/{only}/proof.json")
        ids = [only]
    cache: dict[str, list[str]] = {}
    results = []
    for fid in ids:
        p = build(root, fid, cache)
        fx = root / "fixes" / fid
        (fx / "provenance.json").write_text(scrub(json.dumps(p, indent=1, ensure_ascii=False)) + "\n")
        (fx / "PROVENANCE.md").write_text(render(p))
        results.append(p)
    return results
