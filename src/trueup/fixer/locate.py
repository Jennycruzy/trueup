"""Locate the wrapper behind a finding, and its callers, in a shallow clone of the library.

First choice is Entire's code graph. `entire agent-help` (CLI 0.11.4) lists no graph
command; `entire graph` answers that the entire-graph plugin is not installed, and
`agent-help` marks `entire plugin` as the user's to run, so Trueup does not install
it. Each run probes again and records what the CLI said. When the graph is not
there, the fallback is ripgrep for the seed symbols plus Python's ast for the
enclosing definitions, and locate.json says the graph was not used and why.
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


def probe_graph(clone: Path, seeds: tuple[str, ...], run: Runner = run_cmd) -> dict[str, Any]:
    """Ask the installed Entire CLI for its code graph. Records every command and its output."""
    record: dict[str, Any] = {"used": False, "commands": []}
    if shutil.which("entire") is None:
        record["reason"] = "entire CLI not on PATH"
        return record
    for cmd in (["entire", "agent-help"], ["entire", "agent-help", "labs"], ["entire", "graph", "--help"]):
        try:
            p = run(cmd, clone, 60)
            text = (p.stdout + p.stderr).strip()
            record["commands"].append({"cmd": " ".join(cmd), "exit": p.returncode, "output": text[-3000:]})
        except (OSError, subprocess.TimeoutExpired) as e:
            record["commands"].append({"cmd": " ".join(cmd), "error": type(e).__name__})
    graph = record["commands"][-1]
    out = graph.get("output", "")
    if graph.get("exit") == 0 and "not installed" not in out:
        # The graph answered. Its subcommands are not known to this build, so keep the help
        # and let a person read it; Trueup still uses the fallback for its own results.
        record["reason"] = "entire graph answered, but Trueup has no parser for its output yet; fallback used"
    else:
        record["reason"] = ("entire graph is not available here: " + (out.splitlines()[0] if out else "no output") +
                            ". agent-help lists `entire plugin` as the user's command, so Trueup did not "
                            "install it.")
    return record


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


def locate(root: Path, target: Target, out_dir: Path, run: Runner = run_cmd) -> dict[str, Any]:
    clone, commit = ensure_clone(root, target.library, run)
    graph = probe_graph(clone, target.seeds, run)
    located = locate_symbols(clone, target, run)
    result = {"library": target.library, "code_path": target.code_path, "clone": str(clone), "commit": commit,
              "graph": graph, "method": "entire graph" if graph["used"] else "ripgrep + ast (fallback)",
              **located}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "locate.json").write_text(json.dumps(result, indent=1))
    return result
