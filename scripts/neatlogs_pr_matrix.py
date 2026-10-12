"""Run every current neatlogs finding repro on open PRs touching its wrapper.

This is a maintainer tool, not part of the normal Trueup command.  It keeps the
read-only duplicate review reproducible and restores the clone and venv to main.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 600,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="check run containing findings.json")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path.cwd()
    clone = root / ".trueup/clones/neatlogs"
    py = root / ".trueup/venvs/neatlogs-main/bin/python"
    uv = Path(shutil.which("uv") or "uv")
    findings = json.loads((root / ".trueup/runs" / args.run / "findings.json").read_text())["findings"]
    by_id = {f["id"]: f for f in findings}
    jobs: dict[int, dict[str, object]] = {}
    for finding in findings:
        for pr in finding["dedupe"].get("open_prs_touching_patch_files", []):
            job = jobs.setdefault(pr["number"], {"title": pr["title"], "url": pr["url"], "findings": []})
            job["findings"].append(finding["id"])
    records = []
    try:
        for number, job in sorted(jobs.items()):
            print(f"PR #{number}: {job['title']}", flush=True)
            fetched = run(["git", "fetch", "origin", f"pull/{number}/head:refs/trueup/pr-{number}"], cwd=clone)
            if fetched.returncode:
                records.append({"pr": number, **job, "error": fetched.stderr.strip()[-500:]})
                continue
            run(["git", "checkout", "--detach", f"refs/trueup/pr-{number}"], cwd=clone)
            installed = run([str(uv), "pip", "install", "--quiet", "--no-deps", "--reinstall",
                             "--python", str(py), str(clone)], timeout=900)
            result = {"pr": number, **job, "commit": run(["git", "rev-parse", "HEAD"], cwd=clone).stdout.strip(),
                      "installed": installed.returncode == 0, "repros": []}
            if installed.returncode:
                result["error"] = installed.stderr.strip()[-500:]
            else:
                for finding_id in job["findings"]:
                    script = root / "evidence/findings" / finding_id / "repro.py"
                    env = {**os.environ, "PYTHONPATH": str(root / "src")}
                    repro = run([str(py), str(script)], cwd=root, timeout=180, env=env)
                    emitted = []
                    if repro.returncode == 0:
                        for line in repro.stdout.splitlines():
                            try:
                                emitted.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                    details = by_id[finding_id]["details"]
                    field_kind = lambda value: re.sub(r"^(call \d+ |tool run \d+ \([^)]*\) )", "", value)
                    matching = [lead for lead in emitted if lead.get("check") == details["check"] and
                                field_kind(lead.get("field", "")) == details["field"]]
                    result["repros"].append({"finding": finding_id, "exit": repro.returncode,
                                             "still_reproduces": bool(matching), "matching_leads": matching,
                                             "stdout": repro.stdout.strip(),
                                             "stderr": repro.stderr.strip()[-500:]})
                    verdict = "ERROR" if repro.returncode else ("still broken" if matching else "fixed here")
                    print(f"  {finding_id}: {verdict}", flush=True)
            records.append(result)
    finally:
        run(["git", "checkout", "main"], cwd=clone)
        run([str(uv), "pip", "install", "--quiet", "--no-deps", "--reinstall", "--python", str(py), str(clone)],
            timeout=900)
    output = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "run": args.run,
              "method": "each finding repro on every open PR touching its wrapper file", "pull_requests": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
