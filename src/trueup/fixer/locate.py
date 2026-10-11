"""Locate the wrapper behind a finding, and its callers, in a shallow clone of the library.

First choice is Entire's code graph (the entire-graph plugin), as its agent guide says:
`entire graph capabilities --json` must list Python as a semantic language; then, per
target package, one `entire graph search --profile full` with the finding in one sentence,
and for the top hits `entire graph neighbors --relation CALLS --direction in` (callers) and
`entire graph impact`. The library's own reference pattern comes from a second search.
Every command and its JSON output is kept, with paths relative to the clone.

When the graph is not installed, does not cover Python, fails or finds nothing, the
fallback is ripgrep for the target's seed symbols plus Python's ast for the enclosing
definitions, and locate.json says the graph was not used and why.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from trueup.fixer.targets import REPOS, Target

# Installing a clone (pip/uv build) leaves copies of the source here; they are not the library's code.
BUILD_DIRS = ("build", "dist", ".eggs")

Runner = Callable[[list[str], Path | None, float], subprocess.CompletedProcess]


def run_cmd(cmd: list[str], cwd: Path | None = None, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def clone_dir(root: Path, library: str) -> Path:
    return root.resolve() / ".trueup" / "clones" / library


def ensure_clone(root: Path, library: str, run: Runner = run_cmd) -> tuple[Path, str]:
    """Shallow clone of the library's default branch. Returns (path, commit)."""
    d = clone_dir(root, library)
    if not (d / ".git").exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        p = run(["git", "clone", "--quiet", "--depth", "1", REPOS[library], str(d)], None, 1200)
        if p.returncode != 0:
            raise RuntimeError(f"git clone {REPOS[library]} failed: {p.stderr.strip()[-300:]}")
    p = run(["git", "-C", str(d), "rev-parse", "HEAD"], None, 60)
    return d, p.stdout.strip()


def reset_clone(clone: Path, run: Runner = run_cmd) -> None:
    """Drop every local change in the clone (only the clone)."""
    run(["git", "-C", str(clone), "reset", "--quiet"], None, 120)  # intent-to-add entries from patch.diff
    run(["git", "-C", str(clone), "checkout", "--quiet", "--", "."], None, 120)
    run(["git", "-C", str(clone), "clean", "--quiet", "-fd"], None, 120)


REPO_ROOT = Path(__file__).resolve().parents[3]  # this Trueup checkout
GRAPH_TOP = 3  # search hits followed up with neighbors and impact
GRAPH_TIMEOUT = 600


def scrub(text: str, *roots: Path) -> str:
    """Remove this machine's absolute paths: each root (longest first) becomes relative, home becomes ~."""
    for r in sorted({str(x.resolve()) for x in roots}, key=len, reverse=True):
        text = text.replace(r + "/", "").replace(r, ".")
    home = str(Path.home())
    return text.replace(home + "/", "~/") if home not in ("/", "") else text


def save(path: Path, text: str) -> None:
    """Write a file Trueup may commit, without this machine's absolute paths."""
    path.write_text(scrub(text, REPO_ROOT))


def _graph(cmd: list[str], clone: Path, run: Runner, record: dict[str, Any]) -> Any:
    """Run one `entire graph` command in the clone; record it; parsed JSON or None."""
    entry: dict[str, Any] = {"cmd": " ".join(cmd)}
    record["commands"].append(entry)
    try:
        p = run(cmd, clone, GRAPH_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        entry["error"] = type(e).__name__
        return None
    entry["exit"] = p.returncode
    if p.returncode != 0:
        entry["error"] = (p.stderr or p.stdout).strip()[-500:]
        return None
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        entry["error"] = "output is not JSON: " + p.stdout.strip()[:200]
        return None
    entry["output"] = data
    return data


def probe_graph(clone: Path, run: Runner = run_cmd) -> dict[str, Any]:
    """Is the code graph usable here for Python? Records the check."""
    record: dict[str, Any] = {"used": False, "commands": []}
    if shutil.which("entire") is None:
        record["reason"] = "entire CLI not on PATH"
        return record
    caps = _graph(["entire", "graph", "capabilities", "--json"], clone, run, record)
    if caps is None:
        err = record["commands"][-1].get("error", "")
        record["reason"] = f"entire graph is not available here: {err.splitlines()[0] if err else 'no output'}"
        return record
    # Keep what matters for Python, not the whole language table.
    record["commands"][-1]["output"] = {
        "schema_version": caps.get("schema_version"),
        "python_semantic": "Python" in caps.get("semantic_languages", []),
        "python_relations": caps.get("relation_support_by_language", {}).get("Python", []),
        "network": caps.get("features_requiring_network_access")}
    if "Python" not in caps.get("semantic_languages", []):
        record["reason"] = "entire graph has no semantic support for Python here"
        return record
    record["available"] = True
    return record


def finding_query(finding: dict[str, Any] | None, target: Target) -> str:
    """The finding in one plain sentence, as the graph's agent guide asks."""
    if not finding:
        return f"{target.code_path} wrapper records the wrong span data"
    d = finding["details"]
    ex = d.get("example") or (d.get("leads") or [{}])[0]
    return (f"{target.code_path} tracing: {d['field']} is {ex.get('trace')} in the span but really "
            f"{ex.get('truth')} ({finding['title']})")


def locate_graph(clone: Path, target: Target, query: str, record: dict[str, Any],
                 run: Runner = run_cmd) -> dict[str, Any]:
    """Definitions (ranked search hits), callers and reference uses from the graph, relative to the clone."""
    definitions, callers, reference = [], [], []
    for pkg in target.packages:
        res = _graph(["entire", "graph", "search", "--repo", pkg.path, "--profile", "full", "--format", "json",
                      "--top-k", "8", "--query", query], clone, run, record)
        prefix = "" if pkg.path in (".", "") else pkg.path.rstrip("/") + "/"
        for h in (res or {}).get("results", []):
            if h.get("kind") not in ("function", "method", "class") or "/tests/" in "/" + h["file_path"]:
                continue
            definitions.append({"symbol": h.get("symbol_name"), "qualname": h.get("qualified_name"),
                                "file": prefix + h["file_path"], "line": h.get("symbol_start_line") or h["start_line"],
                                "end": h.get("symbol_end_line") or h["end_line"], "score": h.get("score"),
                                "package": pkg.path})
    definitions.sort(key=lambda d: -(d["score"] or 0))
    for i, d in enumerate(definitions, 1):
        d["rank"] = i
    for d in definitions[:GRAPH_TOP]:
        sym = d["qualname"] or d["symbol"]
        pkg = d["package"]
        file_in_pkg = d["file"][len(pkg.rstrip("/")) + 1:] if pkg not in (".", "") else d["file"]
        prefix = "" if pkg in (".", "") else pkg.rstrip("/") + "/"
        where = ["--file", file_in_pkg]
        nb = _graph(["entire", "graph", "neighbors", "--repo", pkg, "--symbol", d["symbol"], *where, "--relation",
                     "CALLS", "--direction", "in", "--format", "json", "--exclude-tests"], clone, run, record)
        for m in (nb or {}).get("matches", []):
            for e in m.get("incoming", []):
                ep = e["endpoint"]
                callers.append({"symbol": sym, "file": prefix + ep["file_path"] if ep.get("file_path") else None,
                                "line": ep.get("start_line"), "in": ep.get("qualified_name"),
                                "text": "; ".join(x.get("detail", "") for x in e.get("evidence", []))[:200],
                                "confidence": e.get("confidence")})
        _graph(["entire", "graph", "impact", "--repo", pkg, "--symbol", d["symbol"], *where, "--format", "json",
                "--exclude-tests"], clone, run, record)
    if target.reference_seeds:
        base = "packages" if (clone / "packages").is_dir() else "."
        res = _graph(["entire", "graph", "search", "--repo", base, "--profile", "fast", "--format", "json",
                      "--top-k", "8", "--query", "where " + " ".join(target.reference_seeds) +
                      " is used to record the right span"], clone, run, record)
        pre = "" if base == "." else base + "/"
        for h in (res or {}).get("results", []):
            if "/tests/" in "/" + h["file_path"]:
                continue
            reference.append({"symbol": " ".join(target.reference_seeds), "file": pre + h["file_path"],
                              "line": h.get("focus_line") or h["start_line"], "in": h.get("qualified_name"),
                              "text": (h.get("signature") or "")[:200]})
    return {"definitions": definitions, "callers": callers, "reference": reference}


def _defs(tree: ast.AST) -> list[tuple[str, int, int, str]]:
    """(qualname, start, end, kind) for every function and class, nested ones included."""
    out: list[tuple[str, int, int, str]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = f"{prefix}{child.name}"
                kind = "class" if isinstance(child, ast.ClassDef) else "function"
                out.append((q, child.lineno, child.end_lineno or child.lineno, kind))
                walk(child, q + ".")
            else:
                walk(child, prefix)

    walk(tree, "")
    return out


def enclosing(defs: list[tuple[str, int, int, str]], line: int) -> str | None:
    """The innermost function or class around a line."""
    best = None
    for q, a, b, _ in defs:
        if a <= line <= b and (best is None or a >= best[1]):
            best = (q, a)
    return best[0] if best else None


def rg_lines(pattern: str, paths: list[Path], run: Runner = run_cmd) -> list[tuple[Path, int, str]]:
    """ripgrep matches in Python files outside tests: (file, line, text)."""
    rg = shutil.which("rg")
    hits: list[tuple[Path, int, str]] = []
    if rg:
        p = run([rg, "-n", "--no-heading", "--type", "py", "-g", "!tests/**", *(a for d in BUILD_DIRS for a in
                 ("-g", f"!{d}/**")), "-e", pattern,
                 *map(str, paths)], None, 120)
        for ln in p.stdout.splitlines():
            f, n, text = ln.split(":", 2)
            hits.append((Path(f), int(n), text.strip()))
        return hits
    import re  # no ripgrep: same search in Python

    rx = re.compile(pattern)
    for base in paths:
        for f in sorted(base.rglob("*.py")):
            if {"tests", *BUILD_DIRS} & set(f.relative_to(base).parts):
                continue
            for i, text in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if rx.search(text):
                    hits.append((f, i, text.strip()))
    return hits


def locate_symbols(clone: Path, target: Target, run: Runner = run_cmd) -> dict[str, Any]:
    """Definitions of the seeds, their callers, and the reference symbols' uses, via ripgrep + ast."""
    paths = [clone / p.path for p in target.packages]
    trees: dict[Path, list[tuple[str, int, int, str]]] = {}

    def defs_of(f: Path) -> list[tuple[str, int, int, str]]:
        if f not in trees:
            try:
                trees[f] = _defs(ast.parse(f.read_text(errors="replace")))
            except SyntaxError:
                trees[f] = []
        return trees[f]

    rel = lambda f: str(f.resolve().relative_to(clone.resolve()))  # noqa: E731
    definitions, callers = [], []
    for seed in target.seeds:
        for f, n, text in rg_lines(rf"^\s*(async\s+)?(def|class)\s+{seed}\b", paths, run):
            q = enclosing(defs_of(f), n)
            definitions.append({"symbol": seed, "file": rel(f), "line": n, "qualname": q,
                                "end": next((b for qq, a, b, _ in defs_of(f) if qq == q), n)})
        for f, n, text in rg_lines(rf"\b{seed}\b", paths, run):
            if text.lstrip().startswith(("def ", "async def ", "class ", "#", "from ", "import ")):
                continue
            callers.append({"symbol": seed, "file": rel(f), "line": n, "in": enclosing(defs_of(f), n),
                            "text": text[:200]})
    reference = []
    for seed in target.reference_seeds:
        repo_paths = [clone / "packages"] if (clone / "packages").exists() else [clone]
        for f, n, text in rg_lines(rf"\b{seed}\b", repo_paths, run)[:40]:
            if "import" in text:
                continue
            reference.append({"symbol": seed, "file": rel(f), "line": n, "in": enclosing(defs_of(f), n),
                              "text": text[:200]})
    # Places that set a context key or value come first: they show the pattern, the readers only use it.
    reference.sort(key=lambda r: "set_value" not in r["text"] and "attach" not in r["text"])
    return {"definitions": definitions, "callers": callers, "reference": reference}


def source_excerpts(clone: Path, located: dict[str, Any], limit: int = 40_000) -> str:
    """Whole files that define a seed (most relevant first), then a window around reference uses."""
    parts, total, seen = [], 0, set()
    for d in located["definitions"]:
        if d["file"] in seen:
            continue
        seen.add(d["file"])
        text = (clone / d["file"]).read_text(errors="replace")
        if total + len(text) > limit:
            # Verbatim (no line numbers, so edits can quote it): the imports, then the definitions.
            lines = text.splitlines()
            spans = sorted((x["line"], x["end"]) for x in located["definitions"] if x["file"] == d["file"])
            a, b = max(0, spans[0][0] - 30), min(len(lines), spans[-1][1] + 30)
            head = min(a, 70)
            text = ("\n".join(lines[:head]) + f"\n# ... (lines {head + 1}-{a} not shown)\n" if head else "") + \
                "\n".join(lines[a:b]) + (f"\n# ... (lines {b + 1}-{len(lines)} not shown)" if b < len(lines) else "")
        total += len(text)
        parts.append(f"### {d['file']}\n{text}")
    for r in located["reference"][:6]:
        lines = (clone / r["file"]).read_text(errors="replace").splitlines()
        a, b = max(0, r["line"] - 12), min(len(lines), r["line"] + 12)
        parts.append(f"### reference {r['file']}:{a + 1}-{b}\n" + "\n".join(lines[a:b]))
    return "\n\n".join(parts)


def locate(root: Path, target: Target, out_dir: Path, run: Runner = run_cmd,
           finding: dict[str, Any] | None = None) -> dict[str, Any]:
    """Graph first, ripgrep + ast as the fallback. Writes locate.json (no absolute paths); returns the
    result with the clone's absolute path for the caller."""
    clone, commit = ensure_clone(root, target.library, run)
    graph = probe_graph(clone, run)
    located = None
    if graph.get("available"):
        graph["query"] = finding_query(finding, target)
        located = locate_graph(clone, target, graph["query"], graph, run)
        if located["definitions"]:
            graph["used"] = True
            graph["reason"] = "entire graph search, neighbors and impact"
        else:
            graph["reason"] = "entire graph found no function for the query; fallback used"
            located = None
    if located is None:
        located = locate_symbols(clone, target, run)
    result = {"library": target.library, "code_path": target.code_path,
              "clone": f".trueup/clones/{target.library}", "commit": commit, "graph": graph,
              "method": "entire graph" if graph["used"] else "ripgrep + ast (fallback)", **located}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "locate.json").write_text(scrub(json.dumps(result, indent=1), clone, root))
    return {**result, "clone": str(clone)}


def patched_functions(clone: Path, diff_text: str) -> list[dict[str, Any]]:
    """The functions a patch.diff changes: each removed or added line, placed at its line in the
    original file, mapped to the innermost enclosing function with ast. Test files are skipped."""
    import re

    changed: dict[str, set[int]] = {}
    file, line = None, 0
    for ln in diff_text.splitlines():
        if ln.startswith("--- "):
            file = ln[6:] if ln.startswith("--- a/") and "/tests/" not in "/" + ln[6:] else None
            continue
        if ln.startswith("+++ "):
            continue
        m = re.match(r"@@ -(\d+)", ln)
        if m:
            line = int(m.group(1))
            continue
        if file is None or not ln:
            continue
        if ln[0] == "-":
            changed.setdefault(file, set()).add(line)
            line += 1
        elif ln[0] == "+":
            changed.setdefault(file, set()).add(max(line - 1, 1))  # inserted after the previous original line
        elif ln[0] == " ":
            line += 1
    out: list[dict[str, Any]] = []
    for f, lines in changed.items():
        try:
            defs = [d for d in _defs(ast.parse((clone / f).read_text(errors="replace"))) if d[3] == "function"]
        except (OSError, SyntaxError):
            continue
        for q in dict.fromkeys(enclosing(defs, n) for n in sorted(lines)):
            if q:  # an import-only change has no enclosing function
                out.append({"file": f, "qualname": q})
    return out


def compare_with_patch(located: dict[str, Any], patched: list[dict[str, Any]]) -> dict[str, Any]:
    """Where each patched function ranks among the located definitions: an exact hit, or only inside a
    class hit (the class was found, not the method)."""
    rows = []
    for p in patched:
        same_file = [d for d in located["definitions"] if d["file"] == p["file"]]
        exact = next((d for d in same_file if d.get("qualname") == p["qualname"]), None)
        within = next((d for d in same_file if p["qualname"].startswith((d.get("qualname") or "-") + ".")), None)
        caller = any(c.get("in") == p["qualname"] for c in located["callers"])
        rows.append({**p, "rank": exact.get("rank") if exact else None,
                     "class_rank": within.get("rank") if within and not exact else None, "among_callers": caller})
    return {"patched": rows, "found": sum(r["rank"] is not None for r in rows),
            "in_top": sum(r["rank"] is not None and r["rank"] <= GRAPH_TOP for r in rows), "top": GRAPH_TOP,
            "same_function_first": any(r["rank"] == 1 for r in rows)}
