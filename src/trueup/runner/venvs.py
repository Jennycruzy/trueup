"""Per-library venvs under .trueup/venvs/<lib>, built with uv."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from trueup.runner.setups import PACKAGES

STAMP = "trueup-packages.json"


class VenvError(RuntimeError):
    pass


def venv_dir(root: Path, library: str) -> Path:
    return root.resolve() / ".trueup" / "venvs" / library


def python_path(root: Path, library: str) -> Path:
    return venv_dir(root, library) / "bin" / "python"


def is_ready(root: Path, library: str) -> bool:
    stamp = venv_dir(root, library) / STAMP
    if not stamp.exists() or not python_path(root, library).exists():
        return False
    try:
        return json.loads(stamp.read_text()) == PACKAGES[library]
    except ValueError:
        return False


def ensure(root: Path, library: str, timeout: float = 900) -> Path:
    """Create the venv if missing or out of date. Returns its python."""
    if library not in PACKAGES:
        raise VenvError(f"unknown library {library!r}")
    py = python_path(root, library)
    if is_ready(root, library):
        return py
    uv = shutil.which("uv")
    if uv is None:
        raise VenvError("uv not found on PATH")
    d = venv_dir(root, library)
    d.parent.mkdir(parents=True, exist_ok=True)
    steps = [
        [uv, "venv", "--quiet", "--allow-existing", "--python", "3.12", str(d)],
        [uv, "pip", "install", "--quiet", "--python", str(py), *PACKAGES[library]],
    ]
    for cmd in steps:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise VenvError(f"timed out: {' '.join(cmd[:3])}") from None
        if p.returncode != 0:
            raise VenvError(f"{' '.join(cmd[:3])} failed: {(p.stderr or p.stdout).strip()[-500:]}")
    (d / STAMP).write_text(json.dumps(PACKAGES[library]))
    return py


def _run(cmd: list[str], timeout: float, cwd: Path | None = None) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise VenvError(f"timed out: {' '.join(cmd[:3])}") from None
    if p.returncode != 0:
        raise VenvError(f"{' '.join(cmd[:3])} failed: {(p.stderr or p.stdout).strip()[-500:]}")
    return p.stdout


def upgrade(root: Path, library: str, timeout: float = 900) -> Path:
    """Bring the library's venv to the latest releases on PyPI. Returns its python."""
    py = ensure(root, library, timeout)
    uv = shutil.which("uv") or "uv"
    _run([uv, "pip", "install", "--quiet", "--upgrade", "--python", str(py), *PACKAGES[library]], timeout)
    return py


# The library's main branch: repo, and local package paths that replace PyPI distributions.
MAIN_SOURCES: dict[str, dict[str, object]] = {
    "neatlogs": {"repo": "https://github.com/neatlogs/neatlogs", "paths": {"neatlogs": "."}},
    "openinference": {
        "repo": "https://github.com/Arize-ai/openinference",
        "paths": {
            "openinference-semantic-conventions": "python/openinference-semantic-conventions",
            "openinference-instrumentation": "python/openinference-instrumentation",
            **{f"openinference-instrumentation-{n}": f"python/instrumentation/openinference-instrumentation-{n}"
               for n in ("openai", "anthropic", "langchain", "openai-agents")},
        },
    },
    "openllmetry": {
        "repo": "https://github.com/traceloop/openllmetry",
        "paths": {
            "opentelemetry-semantic-conventions-ai": "packages/opentelemetry-semantic-conventions-ai",
            **{f"opentelemetry-instrumentation-{n}": f"packages/opentelemetry-instrumentation-{n}"
               for n in ("openai", "anthropic", "langchain", "openai-agents")},
            "traceloop-sdk": "packages/traceloop-sdk",
        },
    },
}


def clone_dir(root: Path, library: str) -> Path:
    return root.resolve() / ".trueup" / "src" / str(MAIN_SOURCES[library]["repo"]).rsplit("/", 1)[1]


def ensure_main(root: Path, library: str, timeout: float = 1200) -> tuple[Path, str]:
    """Shallow-clone main and install its packages into .trueup/venvs/<lib>-main. Returns (python, commit)."""
    src = MAIN_SOURCES[library]
    paths: dict[str, str] = src["paths"]  # type: ignore[assignment]
    clone = clone_dir(root, library)
    git = shutil.which("git") or "git"
    if not (clone / ".git").exists():
        clone.parent.mkdir(parents=True, exist_ok=True)
        _run([git, "clone", "--quiet", "--depth", "1", str(src["repo"]), str(clone)], timeout)
    commit = _run([git, "-C", str(clone), "rev-parse", "HEAD"], 60).strip()
    d = venv_dir(root, f"{library}-main")
    py = d / "bin" / "python"
    stamp = {"commit": commit, "packages": PACKAGES[library]}
    if py.exists() and (d / STAMP).exists() and json.loads((d / STAMP).read_text()) == stamp:
        return py, commit
    uv = shutil.which("uv") or "uv"
    pypi = [p for p in PACKAGES[library] if p not in paths]
    _run([uv, "venv", "--quiet", "--allow-existing", "--python", "3.12", str(d)], timeout)
    _run([uv, "pip", "install", "--quiet", "--python", str(py), *pypi, *(str(clone / p) for p in paths.values())],
         timeout)
    (d / STAMP).write_text(json.dumps(stamp))
    return py, commit
