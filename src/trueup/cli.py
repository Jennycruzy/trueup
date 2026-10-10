"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from trueup.runner.setups import LIBRARIES

# Exit codes
EXIT_OK = 0  # no mismatches
EXIT_MISMATCH = 1  # mismatches found
EXIT_ERROR = 2  # could not run

KEY_VARS = ("NEATLOGS_API_KEY", "TRUEUP_MODEL_KEY")
NOT_BUILT = ("fix", "upstream", "verify", "report")


def doctor() -> int:
    ok = sys.version_info >= (3, 12)
    v = sys.version_info
    print(f"python: {v.major}.{v.minor}.{v.micro} ({'ok' if ok else 'need 3.12+'})")
    for name in KEY_VARS:
        # Only report presence. Never print the value.
        state = "set" if os.environ.get(name) else "not set"
        print(f"{name}: {state}")
    return EXIT_OK if ok else EXIT_ERROR


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
    au = sub.add_parser("audit", help="run your script's main() against the fake provider and compare its trace")
    au.add_argument("script", type=Path, help="Python file with a main() that calls the openai or anthropic SDK")
    au.add_argument("--library", required=True, choices=LIBRARIES, help="tracing library to set up")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor()
    if args.command == "sweep":
        from trueup.sweep import exit_code, sweep

        _, results = sweep(Path.cwd(), args.library, args.framework)
        return exit_code(results)
    if args.command == "audit":
        from trueup.audit import audit
        from trueup.sweep import exit_code

        _, results = audit(Path.cwd(), args.library, args.script)
        return exit_code(results)
    print(f"trueup {args.command}: not built yet", file=sys.stderr)
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
