"""Command line entry point."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
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


def traced_worker_command(command: str, target: str, worker: str, body: Callable[[], int],
                          run_id: str | None = None) -> int:
    """Run one command as a named worker in a single Neatlogs session.

    Commands remain keyless: when NEATLOGS_API_KEY is absent, the same body runs locally.
    """
    from trueup import tracing
    from trueup.sweep import new_run_id

    rid = run_id or new_run_id(command)

    def wrapped() -> int:
        with tracing.worker(worker, command=command) as span:
            code = body()
            tracing.set_verdict(span, {EXIT_OK: "ok", EXIT_MISMATCH: "mismatch", EXIT_ERROR: "error"}.get(
                code, f"exit {code}"))
            if code == EXIT_ERROR:
                tracing.mark("command could not run", command=command)
            return code

    return tracing.run_traced(rid, target, command, wrapped)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trueup",
        description="Find where AI agent traces disagree with what really happened.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check the local setup")
    sub.add_parser("bundle", help="write the evidence bundle evidence/ from .trueup/runs, fixes/ and upstream/")
    ev = sub.add_parser("evidence", help="collect external evidence used by the bundle")
    evsub = ev.add_subparsers(dest="evidence_command", required=True)
    evsub.add_parser("pull", help="pull detections, analytics and fix suggestions from Neatlogs (read only)")
    dm = sub.add_parser("demo", help="show one complete before/after proof from verified evidence (offline)")
    dm.add_argument("--evidence", type=Path, default=Path("evidence"), help="bundle dir (default evidence)")
    dm.add_argument("--finding", default=None, help="finding id (default: the featured OpenInference proof)")
    vf = sub.add_parser("verify", help="recompute every headline number from evidence/ and check every sha256")
    vf.add_argument("--evidence", type=Path, default=Path("evidence"), help="bundle dir (default evidence)")
    rp = sub.add_parser("report", help="build docs/index.html from evidence/")
    rp.add_argument("--evidence", type=Path, default=Path("evidence"), help="bundle dir (default evidence)")
    rp.add_argument("--out", type=Path, default=Path("docs/index.html"), help="output (default docs/index.html)")
    tr = sub.add_parser("traces", help="read a run's own traces back from neatlogs (MCP server, read only)")
    tr.add_argument("session_id", help="a run id (= neatlogs session id)")
    sw = sub.add_parser("sweep", help="run the scenarios against one tracing library")
    sw.add_argument("library", choices=LIBRARIES)
    sw.add_argument("--framework", default="all", choices=("all", "none", "langchain", "openai-agents"),
                    help="none: plain SDK; langchain: LangChain and LangGraph; default all")
    sw.add_argument("--provider", default="openai,anthropic", metavar="LIST",
                    help="comma-separated providers: openai,anthropic (default both)")
    sw.add_argument("--case", action="append", metavar="SCENARIO",
                    help="run only this scenario id (repeatable), e.g. ag-run")
    sw.add_argument("--resume", metavar="RUN_ID",
                    help="resume this run from .trueup/state.db instead of creating a new run")
    sw.add_argument("--proposed", nargs="?", const="", metavar="FROM",
                    help="sweep accepted planner proposals from scenarios/proposed/<FROM> (default: this library)")
    pl = sub.add_parser("plan", help="ask the model for new scenarios (data only), keep the ones code accepts")
    pl.add_argument("library", choices=LIBRARIES)
    pl.add_argument("--max", type=int, default=5, help="most proposals to ask for (default 5)")
    pl.add_argument("--variant", choices=("v1", "v2"), default="v2", help="planner version (default v2)")
    pl.add_argument("--save-dir", type=Path, help="save accepted proposals under DIR/<lib>/ instead of "
                                                  "scenarios/proposed/")
    au = sub.add_parser("audit", help="run your script's main() against the fake provider and compare its trace")
    au.add_argument("script", type=Path, help="Python file with a main() that calls the openai or anthropic SDK")
    au.add_argument("--library", required=True, choices=LIBRARIES, help="tracing library to set up")
    au.add_argument("--cases", choices=("builtin", "mine"), default="builtin",
                    help="built-in failure cases or .trueup/cases/*.json (default builtin)")
    au.add_argument("--resume", metavar="RUN_ID",
                    help="resume this run from .trueup/state.db instead of creating a new run")
    au.add_argument("--record", action="store_true",
                    help="opt in to one real-provider run through the local redacting recording proxy")
    au.add_argument("--provider", choices=("openai", "anthropic"),
                    help="provider used by the script (required with --record)")
    au.add_argument("--upstream", help="provider origin; defaults to TRUEUP_RECORD_UPSTREAM")
    au.add_argument("--neatlogs", action="store_true",
                    help="send mismatch markers to your Neatlogs project with SDK PII redaction enabled")
    fx = sub.add_parser("fix", help="draft a patch and a test for a finding, verify it, write fixes/<id>/")
    fx.add_argument("finding_id", help="a finding id from findings.json")
    fx.add_argument("--tries", type=int, default=3, help="most patch tries (default 3)")
    fx.add_argument("--variant", choices=("v1", "v2"), default="v2", help="fixer version (default v2)")
    fx.add_argument("--reprove", action="store_true",
                    help="apply fixes/<id>/patch.diff to the clean clone, sweep every scenario again and write "
                         "proof.json (no model call)")
    fx.add_argument("--out-dir", type=Path, help="write the fix files here instead of fixes/<id>/")
    fx.add_argument("--locate-only", action="store_true",
                    help="only re-run the locate step and compare it with fixes/<id>/patch.diff (no model call)")
    up = sub.add_parser("upstream", help="draft issue and PR text for a finding into upstream/<id>/ (never posts)")
    up.add_argument("finding_id", help="a finding id from findings.json")
    ck = sub.add_parser("check", help="run the checker and dedupe over a sweep's leads")
    ck.add_argument("run_id", help="a run id under .trueup/runs, or latest")
    ck.add_argument("--library", choices=LIBRARIES, help="with latest: the newest sweep of this library")
    for command_parser in sub.choices.values():
        command_parser.add_argument("--json", action="store_true", help="emit one machine-readable JSON result")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.json:
        return dispatch(args)
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = dispatch(args)
    payload = {
        "command": args.command,
        "exit_code": code,
        "status": "ok" if code == EXIT_OK else "mismatch" if code == EXIT_MISMATCH else "error",
        "stdout": stdout.getvalue().splitlines(),
        "stderr": stderr.getvalue().splitlines(),
    }
    print(json.dumps(payload, separators=(",", ":"), default=str))
    return code


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        return doctor()
    if args.command == "bundle":
        from trueup.evidence import build

        def bundle_body() -> int:
            build(Path.cwd())
            return EXIT_OK

        return traced_worker_command("bundle", "evidence", "trueup-reporter", bundle_body)
    if args.command == "evidence":
        from trueup.neatlogs_evidence import pull
        from trueup.neatlogs_read import NeatlogsReadError

        try:
            pull(Path.cwd())
        except (NeatlogsReadError, OSError, ValueError, json.JSONDecodeError) as e:
            print(f"trueup evidence pull: {e}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_OK
    if args.command == "demo":
        from trueup.demo import DEFAULT_FINDING, DemoError, demo
        from trueup.evidence import VerifyFailed

        def demo_body() -> int:
            try:
                demo(args.evidence, args.finding or DEFAULT_FINDING)
            except (DemoError, VerifyFailed, FileNotFoundError, json.JSONDecodeError, KeyError) as e:
                print(f"trueup demo: {e}", file=sys.stderr)
                return EXIT_MISMATCH
            return EXIT_OK

        return traced_worker_command("demo", "evidence", "trueup-reporter", demo_body)
    if args.command == "verify":
        from trueup.evidence import VerifyFailed, print_headline, verify

        def verify_body() -> int:
            try:
                print_headline(verify(args.evidence))
            except (VerifyFailed, FileNotFoundError, json.JSONDecodeError, KeyError) as e:
                print(f"trueup verify: FAILED\n{e}", file=sys.stderr)
                return EXIT_MISMATCH
            print("verify: OK (every sha256 matches; every number recomputed)")
            return EXIT_OK

        return traced_worker_command("verify", "evidence", "trueup-reporter", verify_body)
    if args.command == "report":
        from trueup.evidence import VerifyFailed, verify
        from trueup.report_html import write

        def report_body() -> int:
            try:
                verify(args.evidence, out=lambda _: None)
            except VerifyFailed as e:
                print(f"trueup report: the bundle does not verify; no page written\n{e}", file=sys.stderr)
                return EXIT_MISMATCH
            print(f"wrote {write(args.evidence, args.out)}")
            return EXIT_OK

        return traced_worker_command("report", "evidence", "trueup-reporter", report_body)
    if args.command == "traces":
        from trueup.neatlogs_read import NeatlogsReadError, Reader, session

        try:
            s = session(Reader(), args.session_id)
        except NeatlogsReadError as e:
            print(f"trueup traces: {e}", file=sys.stderr)
            return EXIT_ERROR
        print(json.dumps(s, indent=1))
        return EXIT_OK
    if args.command == "sweep":
        from trueup import tracing
        from trueup.sweep import exit_code, sweep
        from trueup.sweep import new_run_id

        proposed = None if args.proposed is None else (args.proposed or args.library)
        if proposed is not None and proposed not in LIBRARIES:
            print(f"trueup sweep: --proposed must name a library: {', '.join(LIBRARIES)}", file=sys.stderr)
            return EXIT_ERROR
        run_id = args.resume or (new_run_id(args.library) + ("-proposed" if proposed else ""))
        providers = tuple(dict.fromkeys(x.strip() for x in args.provider.split(",") if x.strip()))
        unknown_providers = set(providers) - {"openai", "anthropic"}
        if not providers or unknown_providers:
            bad = ", ".join(sorted(unknown_providers)) or "empty list"
            print(f"trueup sweep: invalid --provider: {bad}", file=sys.stderr)
            return EXIT_ERROR

        def sweep_body() -> int:
            try:
                _, results = sweep(Path.cwd(), args.library, args.framework, proposed=proposed, cases=args.case,
                                   run_id=run_id, providers=providers)
            except (KeyError, ValueError) as e:
                print(f"trueup sweep: {e.args[0]}", file=sys.stderr)
                return EXIT_ERROR
            return exit_code(results)

        return tracing.run_traced(run_id, args.library, "sweep", sweep_body)
    if args.command == "plan":
        return plan_command(args.library, args.max, args.variant, args.save_dir)
    if args.command == "audit":
        from trueup import tracing
        from trueup.audit import audit
        from trueup.sweep import exit_code, new_run_id

        if args.record and not args.provider:
            print("trueup audit: --record requires --provider openai|anthropic", file=sys.stderr)
            return EXIT_ERROR
        if (args.provider or args.upstream) and not args.record:
            print("trueup audit: --provider/--upstream require --record", file=sys.stderr)
            return EXIT_ERROR
        if args.record and args.cases != "builtin":
            print("trueup audit: --record cannot be combined with --cases mine", file=sys.stderr)
            return EXIT_ERROR
        run_id = args.resume or new_run_id(args.library).replace(f"-{args.library}", f"-audit-{args.library}")

        def audit_body() -> int:
            try:
                _, results = audit(Path.cwd(), args.library, args.script, run_id=run_id,
                                   record_provider=args.provider if args.record else None,
                                   upstream=args.upstream or os.environ.get("TRUEUP_RECORD_UPSTREAM"), cases=args.cases,
                                   neatlogs=args.neatlogs)
            except ValueError as error:
                print(f"trueup audit: {error}", file=sys.stderr)
                return EXIT_ERROR
            return exit_code(results)

        return tracing.run_traced(run_id, args.library, "audit", audit_body, pii_enabled=args.neatlogs)
    if args.command == "check":
        from trueup import tracing
        from trueup.check import check
        from trueup.sweep import new_run_id

        check_run_id = new_run_id(f"check-{args.library or 'latest'}")

        def check_body() -> int:
            try:
                res = check(Path.cwd(), args.run_id, args.library, state_run_id=check_run_id)
            except (FileNotFoundError, ValueError) as e:
                print(f"trueup check: {e}", file=sys.stderr)
                return EXIT_ERROR
            return EXIT_MISMATCH if res["counts"]["findings"] else EXIT_OK

        return tracing.run_traced(check_run_id, args.library or "check", "check", check_body)
    if args.command == "fix":
        if args.reprove:
            from trueup.fix import reprove

            def reprove_body() -> int:
                try:
                    proof = reprove(Path.cwd(), args.finding_id)
                except (KeyError, FileNotFoundError, RuntimeError) as e:
                    print(f"trueup fix: {e}", file=sys.stderr)
                    return EXIT_ERROR
                return EXIT_MISMATCH if proof["new_mismatches"] else EXIT_OK

            return traced_worker_command("reprove", args.finding_id, "trueup-verifier", reprove_body)
        if args.locate_only:
            from trueup.fix import locate_only

            def locate_body() -> int:
                try:
                    locate_only(Path.cwd(), args.finding_id)
                except (KeyError, FileNotFoundError, RuntimeError) as e:
                    print(f"trueup fix: {e}", file=sys.stderr)
                    return EXIT_ERROR
                return EXIT_OK

            return traced_worker_command("locate", args.finding_id, "trueup-fixer", locate_body)
        return fix_command(args.finding_id, args.tries, args.variant, args.out_dir)
    if args.command == "upstream":
        from trueup.upstream import upstream

        def upstream_body() -> int:
            try:
                upstream(Path.cwd(), args.finding_id)
            except (FileNotFoundError, KeyError, ValueError) as e:
                print(f"trueup upstream: {e}", file=sys.stderr)
                return EXIT_ERROR
            return EXIT_OK

        return traced_worker_command("upstream", args.finding_id, "trueup-reporter", upstream_body)
    return EXIT_ERROR


def plan_command(library: str, max_n: int, variant: str = "v2", save_dir: Path | None = None) -> int:
    from trueup import tracing
    from trueup.model import ModelError
    from trueup.planner import plan
    from trueup.sweep import new_run_id

    run_id = new_run_id(f"plan-{library}")

    def body() -> int:
        try:
            res = plan(Path.cwd(), library, max_n, run_id=run_id, variant=variant, save_dir=save_dir)
        except (ModelError, FileNotFoundError) as e:
            print(f"trueup plan: {e}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_ERROR if res["error"] else EXIT_OK

    return tracing.run_traced(run_id, library, "plan", body, variant=variant)


def fix_command(finding_id: str, tries: int, variant: str = "v2", out_dir: Path | None = None) -> int:
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
            res = fix(Path.cwd(), finding_id, run_id=run_id, max_tries=tries, variant=variant, out_dir=out_dir)
        except (KeyError, FileNotFoundError) as e:
            print(f"trueup fix: {e}", file=sys.stderr)
            return EXIT_ERROR
        if res["error"]:
            return EXIT_ERROR
        return EXIT_OK if res["fixed"] else EXIT_MISMATCH

    return tracing.run_traced(run_id, finding["library"], "fix", body, variant=variant)


if __name__ == "__main__":
    sys.exit(main())
