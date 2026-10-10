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
