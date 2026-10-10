Trueup finds where your AI agent's traces disagree with what really happened, fixes the tracing code, and proves the fix.

## What it does

Teams watch their AI agents through tracing libraries such as neatlogs, OpenInference and OpenLLMetry. These libraries wrap the AI provider's SDK and record each call. When a wrapper gets a case wrong, the dashboard can show a crashed run as OK, miss a refusal, or show twice the real cost.

Trueup runs the agent against a fake provider, so it knows what really happened. It captures what the trace says and compares the two. When they disagree, it looks for the cause in the tracing library, writes a fix with a test, and checks that the fix works.

The work is split into small workers: planner, runner, comparer, checker, deduper, fixer, verifier and reporter. A language model proposes; plain code decides.

## Status: early build

`trueup doctor`, `trueup sweep <neatlogs|openinference|openllmetry>`, `trueup audit <script> --library <lib>` and `trueup check <run_id|latest> --library <lib>` work.

`sweep` runs the scenarios (plain SDK, LangChain/LangGraph and the OpenAI Agents SDK; pick with `--framework`) against a fake provider, compares truth with the trace, prints a table of leads and writes truth, trace and `leads.json` to `.trueup/runs/<run_id>/`. A lead is a disagreement between truth and trace; it is not a confirmed bug.

`audit` runs your script's `main()` against the fake (through `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL`) under the chosen library, once per fake scenario on each provider route the script calls, and compares the same way. It needs a `main()` with no arguments that uses the `openai` or `anthropic` SDK; see `src/trueup/audit.py` for its limits.

`check` runs the checker over a sweep's leads. A lead becomes a finding only if it reproduces twice in fresh processes, on the recommended setup, on the latest release and on the library's main branch, the fake really sent what truth says, the harness is sane, another library or the OpenTelemetry conventions show the right behaviour, and a repro under 40 lines shows it. Otherwise it is withdrawn with the rule that failed (kept and counted). Findings that share a cause are grouped, then searched for in the library's GitHub issues and PRs (read only). It writes `findings.json` and `withdrawn.json` in the run dir.

The other commands (`fix`, `upstream`, `verify`, `report`) print "not built yet" and exit 2.

Exit codes: 0 no leads, 1 leads found, 2 could not run.

## Run it

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run trueup doctor
uv run pytest -q         # offline unit tests
uv run pytest -q -m e2e  # builds per-library venvs, runs subprocesses
uv run trueup sweep neatlogs
uv run trueup sweep openllmetry --framework openai-agents
uv run trueup audit examples/agent.py --library openinference
uv run trueup check latest --library neatlogs
```

## License

MIT. See [LICENSE](LICENSE).
