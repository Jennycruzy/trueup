"""The model drafts the smallest change plus a unit test; code checks and applies it to the clone.

The draft is JSON: exact search/replace edits on files of the target's packages,
and one new test file in the package's tests directory. Code refuses edits outside
those packages, an `old` text that is not found exactly once, and a test file
outside the tests directory. Whether the patch is kept is decided by verify.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from trueup.fixer.targets import Target

SYSTEM = """You fix bugs in AI tracing libraries (OpenTelemetry instrumentations). Trueup ran a real agent \
against a fake provider, so it knows what really happened, and found that the library's spans disagree with it. \
You get the finding, the located wrapper code and its callers, and how the right behaviour looks.

Draft the SMALLEST change that makes the spans match what happened, in the library's own style, plus ONE new \
unit test written like the package's existing tests (same fixtures, same imports, no network, no API keys, no \
cassettes) that fails on the current code and passes with your change. The test must check the outcome a user \
sees (the spans exported, their count, status or attributes), driving the real code path as far as the \
package's tests do (for example a real SDK client with an httpx.MockTransport), not only that some internal \
flag is set. Do not change existing tests. Do not \
reformat code you do not change.

Reply with JSON only:
{"explanation": "cause and fix in 2-4 plain sentences",
 "edits": [{"file": "<path from the repo root>", "old": "<exact text in the file, unique, with enough context>", \
"new": "<replacement>"}],
 "test": {"file": "<path from the repo root, in the package's tests dir, new file named test_trueup_*.py>", \
"content": "<the whole test file>"}}"""


class PatchError(ValueError):
    """The draft cannot be applied. The reason goes back to the model."""


def test_style(clone: Path, target: Target, limit: int = 14_000) -> str:
    """conftest.py and the shortest test files of the first package, to show its test style."""
    tests = clone / target.packages[0].path / target.packages[0].tests
    parts, total = [], 0
    files = [tests / "conftest.py"] + sorted((f for f in tests.glob("test_*.py")), key=lambda f: f.stat().st_size)
    for f in files:
        if not f.exists():
            continue
        text = f.read_text(errors="replace")[:8000]
        if total + len(text) > limit:
            break
        total += len(text)
        parts.append(f"### {f.relative_to(clone)}\n{text}")
    return "\n\n".join(parts)


def code_path_prefix(scenario_id: str) -> str:
    """Scenarios on one code path share an id prefix: "ag-" for ag-run, "p-an-" for planner proposals."""
    parts = scenario_id.split("-")
    return "-".join(parts[:2 if parts[0] == "p" else 1]) + "-"


def span_summary(run_dirs: list[Path], finding: dict[str, Any]) -> dict[str, Any]:
    """What the library exported before the patch, for every scenario on the finding's code path
    (same id prefix), with what really happened: span name, status, description, parent name."""
    prefixes = {code_path_prefix(sid) for sid in finding["details"]["scenarios"]}
    out: dict[str, Any] = {}
    for f in sorted(f for d in run_dirs for f in d.glob("*.json")):
        if not f.stem.startswith(tuple(prefixes)):
            continue
        r = json.loads(f.read_text())
        if not isinstance(r, dict) or not r.get("observation"):
            continue
        t, spans = r["observation"]["truth"], r["observation"]["trace"]["spans"]
        names = {s.get("span_id"): s["name"] for s in spans}
        out[f.stem] = {
            "app": t["app"]["outcome"] if t["outcome"] == "ok" else f"raised {t.get('exception')}",
            "in_finding": f.stem in finding["details"]["scenarios"],
            "spans": [[s["name"], s["status"]["code"], (s["status"].get("description") or "")[:80],
                       names.get(s.get("parent_id"))] for s in spans]}
    return out


# v2: the reply must start with "{". v1's fixer replies sometimes opened with prose ("Let me look more
# carefully at the exact import text ...", session 20261011T000336Z-fix-openllmetry in neatlogs), and each
# one cost a full re-send of a ~25k-token prompt: 14 of v1's 40 fixer calls were JSON retries.
JSON_ONLY = "\n\nThe first character of your reply is \"{\". No text before or after the JSON."


def first_prompt(finding: dict[str, Any], target: Target, located: dict[str, Any], source: str,
                 style: str, spans: dict[str, Any] | None = None, variant: str = "v1") -> list[dict[str, str]]:
    from trueup import tracing
    from trueup.managed_prompts import production

    d = finding["details"]
    leads = [{k: x.get(k) for k in ("scenario", "field", "truth", "trace")} for x in d.get("leads", [])]
    user = (f"Library: {target.library} (repo commit {located['commit'][:10]}).\n"
            f"Finding {finding['id']}: {finding['title']} (severity {finding['severity']}).\n"
            f"Check: {d['check']}; field: {d['field']}.\nTruth vs trace per scenario:\n{json.dumps(leads)}\n"
            f"Scenarios: {', '.join(d['scenarios'])}. Scenarios of this code path that are right today must stay "
            f"right.\nRight behaviour: {target.reference_note}\nChecker's reference rule: "
            f"{d.get('rules', {}).get('reference', '')}\n\n"
            f"Spans exported before the patch on this code path (scenario: what the app really saw, and "
            f"[name, status, description, parent]). Scenarios not in the finding are right today and must stay "
            f"right:\n{json.dumps(spans or {})}\n\n"
            f"Packages you may change: {', '.join(p.path for p in target.packages)}.\n"
            f"Located definitions:\n{json.dumps(located['definitions'])}\n"
            f"Callers:\n{json.dumps(located['callers'][:60])}\n\n"
            f"Source:\n{source}\n\nTest style of {target.packages[0].path}:\n{style}")
    local_v3 = Path(__file__).resolve().parents[3] / "prompts" / "fixer-v3.txt"
    fallback = local_v3.read_text() if variant == "v3" and local_v3.exists() \
        else SYSTEM + (JSON_ONLY if variant == "v2" else "")
    system = production(f"trueup-fixer-{variant}", fallback, enabled=tracing.active())
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def revision_prompt_v2(first: list[dict[str, str]], draft: Any, reason: str,
                       earlier: list[str]) -> list[dict[str, str]]:
    """v2: the first prompt, the last draft and why it failed, and one line per earlier failed try.
    v1 sent every earlier draft back each time, so a third try's prompt carried two full drafts
    (session 20261011T003256Z-fix-openinference: 140,607 input tokens over 6 calls)."""
    past = "".join(f"\n- try {i}: {r[:300]}" for i, r in enumerate(earlier, 1))
    return [*first, {"role": "assistant", "content": json.dumps(draft)},
            {"role": "user", "content": "That patch was rejected:\n" + reason +
             (f"\n\nEarlier tries were rejected too:{past}" if past else "") +
             "\n\nRevise it. Reply with the whole JSON again (edits against the ORIGINAL files, the full test "
             "file)." + JSON_ONLY}]


def revision_prompt(messages: list[dict[str, str]], draft: Any, reason: str) -> list[dict[str, str]]:
    return [*messages, {"role": "assistant", "content": json.dumps(draft)},
            {"role": "user", "content": "That patch was rejected:\n" + reason +
             "\n\nRevise it. Reply with the whole JSON again (edits against the ORIGINAL files, the full test "
             "file)."}]


def check_draft(draft: Any, clone: Path, target: Target) -> list[dict[str, str]]:
    """The edits plus the test as file writes. Raises PatchError with the reason."""
    if not isinstance(draft, dict) or not isinstance(draft.get("edits"), list) or not draft["edits"]:
        raise PatchError('the reply needs a non-empty "edits" list')
    test = draft.get("test")
    if not isinstance(test, dict) or not test.get("file") or not test.get("content"):
        raise PatchError('the reply needs "test": {"file", "content"}')
    allowed = [p.path.strip("./") for p in target.packages]
    allowed = [a + "/" if a else "" for a in allowed]

    from trueup.fixer.locate import BUILD_DIRS

    def inside(path: str) -> bool:
        parts = Path(path).parts
        return not Path(path).is_absolute() and ".." not in parts and not set(BUILD_DIRS) & set(parts) and any(
            path.startswith(a) for a in allowed)

    files: dict[str, str] = {}
    for e in draft["edits"]:
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) for k in ("file", "old", "new")):
            raise PatchError('each edit needs string "file", "old" and "new"')
        f = e["file"]
        if not inside(f) or "/tests/" in f"/{f}":
            raise PatchError(f"edit to {f} is outside the library code you may change ({', '.join(allowed)})")
        path = clone / f
        if not path.exists():
            raise PatchError(f"{f} does not exist")
        text = files.get(f, path.read_text())
        n = text.count(e["old"])
        if n != 1:
            raise PatchError(f"the old text of an edit to {f} is found {n} times, not once: "
                             f"{e['old'][:120]!r}" + (nearest(text, e["old"]) if n == 0 else ""))
        files[f] = text.replace(e["old"], e["new"], 1)
    tf = test["file"]
    pkg = next((p for p in target.packages if tf.startswith((p.path.strip("./") + "/" if p.path.strip("./") else "")
                                                              + p.tests + "/")), None)
    if pkg is None or not inside(tf) or not Path(tf).name.startswith("test_trueup_") or not tf.endswith(".py"):
        raise PatchError(f"the test file {tf} must be a new test_trueup_*.py in a package's tests dir")
    if (clone / tf).exists():
        raise PatchError(f"the test file {tf} already exists")
    for f, text in files.items():
        try:
            compile(text, f, "exec")
        except SyntaxError as e:
            raise PatchError(f"{f} does not compile after the edits: {e.msg} at line {e.lineno}") from None
    try:
        compile(test["content"], tf, "exec")
    except SyntaxError as e:
        raise PatchError(f"the test file does not compile: {e.msg} at line {e.lineno}") from None
    return [{"file": f, "content": t} for f, t in files.items()]


def nearest(text: str, old: str) -> str:
    """The lines of the file most like the first line of `old`, to show what is really there."""
    import difflib

    first = next((ln for ln in old.splitlines() if ln.strip()), "")
    lines = text.splitlines()
    best = difflib.get_close_matches(first, lines, n=1, cutoff=0.5)
    if not best:
        return ". No similar line in the file."
    i = lines.index(best[0])
    return ". The file really has, from line " + str(i + 1) + ":\n" + "\n".join(lines[i: i + 8])


def write_files(clone: Path, writes: list[dict[str, str]]) -> None:
    for w in writes:
        p = clone / w["file"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(w["content"])


def diff(clone: Path) -> str:
    """git diff of the clone, new files included."""
    subprocess.run(["git", "-C", str(clone), "add", "-N", "."], capture_output=True, timeout=60)
    p = subprocess.run(["git", "-C", str(clone), "diff"], capture_output=True, text=True, timeout=60)
    return p.stdout
