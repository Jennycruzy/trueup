"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from trueup.runner.setups import LIBRARIES

# Exit codes
EXIT_OK = 0  # no mismatches
EXIT_MISMATCH = 1  # mismatches found
EXIT_ERROR = 2  # could not run

KEY_VARS = ("NEATLOGS_API_KEY", "NEATLOGS_PROJECT", "TRUEUP_MODEL_KEY", "TRUEUP_MODEL_BASE_URL")
NOT_BUILT = ("verify", "report")
NEATLOGS_ENDPOINT = "https://ingest.neatlogs.com"


def doctor(http_get: Callable[..., Any] | None = None) -> int:
    ok = sys.version_info >= (3, 12)
    v = sys.version_info
    print(f"python: {v.major}.{v.minor}.{v.micro} ({'ok' if ok else 'need 3.12+'})")
    for name in KEY_VARS:
        # Only report presence. Never print the value.
        state = "set" if os.environ.get(name) else "not set"
        print(f"{name}: {state}")
    print(f"neatlogs: {reach_neatlogs(http_get)}")
    print(f"model proxy: {reach_model(http_get)}")
    return EXIT_OK if ok else EXIT_ERROR


def _get(http_get: Callable[..., Any] | None, url: str, **kw: Any) -> Any:
    import httpx

    kw.setdefault("timeout", 10)
    return (http_get or httpx.get)(url, **kw)


def reach_neatlogs(http_get: Callable[..., Any] | None = None) -> str:
    """One GET to the neatlogs ingest endpoint. Any HTTP reply means reachable."""
    url = os.environ.get("NEATLOGS_ENDPOINT") or NEATLOGS_ENDPOINT
    try:
        return f"reachable (HTTP {_get(http_get, url).status_code})"
    except Exception as e:  # noqa: BLE001
        return f"not reachable ({type(e).__name__})"


def reach_model(http_get: Callable[..., Any] | None = None) -> str:
    """One GET to <proxy>/key/info (no model call): reachable, key accepted, spend against the limit."""
    from trueup.model import BASE_VAR, KEY_VAR, SPEND_LIMIT, ModelError, get_spend

    if not os.environ.get(BASE_VAR) or not os.environ.get(KEY_VAR):
        return f"not checked ({BASE_VAR} or {KEY_VAR} not set)"
    try:
        spend = get_spend(os.environ[BASE_VAR], os.environ[KEY_VAR], lambda u, **kw: _get(http_get, u, **kw))
    except ModelError as e:
        return f"reachable, but {e}"
    except Exception as e:  # noqa: BLE001
        return f"not reachable ({type(e).__name__})"
    return f"reachable, key spend ${spend:.4f} of ${SPEND_LIMIT:.2f} limit"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trueup",
        description="Find where AI agent traces disagree with what really happened.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in NOT_BUILT:
        sub.add_parser(name, help="not built yet")
    sub.add_parser("doctor", help="check the local setup")
    sw = sub.add_parser("sweep", help="run the scenarios against one tracing library")
    sw.add_argument("library", choices=LIBRARIES)
    sw.add_argument("--framework", default="all", choices=("all", "none", "langchain", "openai-agents"),
                    help="none: plain SDK; langchain: LangChain and LangGraph; default all")
    sw.add_argument("--proposed", nargs="?", const="", metavar="FROM",
                    help="sweep accepted planner proposals from scenarios/proposed/<FROM> (default: this library)")
    pl = sub.add_parser("plan", help="ask the model for new scenarios (data only), keep the ones code accepts")
    pl.add_argument("library", choices=LIBRARIES)
    pl.add_argument("--max", type=int, default=5, help="most proposals to ask for (default 5)")
    au = sub.add_parser("audit", help="run your script's main() against the fake provider and compare its trace")
    au.add_argument("script", type=Path, help="Python file with a main() that calls the openai or anthropic SDK")
    au.add_argument("--library", required=True, choices=LIBRARIES, help="tracing library to set up")
    fx = sub.add_parser("fix", help="draft a patch and a test for a finding, verify it, write fixes/<id>/")
    fx.add_argument("finding_id", help="a finding id from findings.json")
    fx.add_argument("--tries", type=int, default=3, help="most patch tries (default 3)")
    up = sub.add_parser("upstream", help="draft issue and PR text for a finding into upstream/<id>/ (never posts)")
    up.add_argument("finding_id", help="a finding id from findings.json")
    ck = sub.add_parser("check", help="run the checker and dedupe over a sweep's leads")
    ck.add_argument("run_id", help="a run id under .trueup/runs, or latest")
    ck.add_argument("--library", choices=LIBRARIES, help="with latest: the newest sweep of this library")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor()
    if args.command == "sweep":
        from trueup.sweep import exit_code, sweep

        proposed = None if args.proposed is None else (args.proposed or args.library)
        if proposed is not None and proposed not in LIBRARIES:
            print(f"trueup sweep: --proposed must name a library: {', '.join(LIBRARIES)}", file=sys.stderr)
            return EXIT_ERROR
        _, results = sweep(Path.cwd(), args.library, args.framework, proposed=proposed)
        return exit_code(results)
    if args.command == "plan":
        return plan_command(args.library, args.max)
    if args.command == "audit":
        from trueup.audit import audit
        from trueup.sweep import exit_code

        _, results = audit(Path.cwd(), args.library, args.script)
        return exit_code(results)
    if args.command == "check":
        from trueup.check import check

        try:
            res = check(Path.cwd(), args.run_id, args.library)
        except (FileNotFoundError, ValueError) as e:
            print(f"trueup check: {e}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_MISMATCH if res["counts"]["findings"] else EXIT_OK
    if args.command == "fix":
        return fix_command(args.finding_id, args.tries)
    if args.command == "upstream":
        from trueup.upstream import upstream

        try:
            upstream(Path.cwd(), args.finding_id)
        except (FileNotFoundError, KeyError, ValueError) as e:
            print(f"trueup upstream: {e}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_OK
    print(f"trueup {args.command}: not built yet", file=sys.stderr)
    return EXIT_ERROR


def plan_command(library: str, max_n: int) -> int:
    from trueup import tracing
    from trueup.model import ModelError
    from trueup.planner import plan
    from trueup.sweep import new_run_id

    run_id = new_run_id(f"plan-{library}")

    def body() -> int:
        try:
            res = plan(Path.cwd(), library, max_n, run_id=run_id)
        except (ModelError, FileNotFoundError) as e:
            print(f"trueup plan: {e}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_ERROR if res["error"] else EXIT_OK

    return tracing.run_traced(run_id, library, "plan", body)


def fix_command(finding_id: str, tries: int) -> int:
    from trueup import tracing
    from trueup.fix import find_finding, fix
    from trueup.sweep import new_run_id

    try:
        finding, _ = find_finding(Path.cwd(), finding_id)
    except FileNotFoundError as e:
        print(f"trueup fix: {e}", file=sys.stderr)
        return EXIT_ERROR
    run_id = new_run_id(f"fix-{finding['library']}")

    def body() -> int:
        try:
            res = fix(Path.cwd(), finding_id, run_id=run_id, max_tries=tries)
        except (KeyError, FileNotFoundError) as e:
            print(f"trueup fix: {e}", file=sys.stderr)
            return EXIT_ERROR
        if res["error"]:
            return EXIT_ERROR
        return EXIT_OK if res["fixed"] else EXIT_MISMATCH

    return tracing.run_traced(run_id, finding["library"], "fix", body)


if __name__ == "__main__":
    sys.exit(main())
