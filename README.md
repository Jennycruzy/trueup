Trueup finds where your AI agent's traces disagree with what really happened, fixes the tracing code, and proves the fix.

## What it does

Teams watch their AI agents through tracing libraries such as neatlogs, OpenInference and OpenLLMetry. These libraries wrap the AI provider's SDK and record each call. When a wrapper gets a case wrong, the dashboard can show a crashed run as OK, miss a refusal, or show twice the real cost.

Trueup runs the agent against a fake provider, so it knows what really happened. It captures what the trace says and compares the two. When they disagree, it looks for the cause in the tracing library, writes a fix with a test, and checks that the fix works.

The work is split into small workers: planner, runner, comparer, checker, deduper, fixer, verifier and reporter. A language model proposes; plain code decides.

## Status: early build

`trueup doctor`, `trueup sweep <neatlogs|openinference|openllmetry>`, `trueup audit <script> --library <lib>`, `trueup check <run_id|latest> --library <lib>` and `trueup plan <lib> [--max N]` work.

`sweep` runs the scenarios (plain SDK, LangChain/LangGraph and the OpenAI Agents SDK; pick with `--framework`) against a fake provider, compares truth with the trace, prints a table of leads and writes truth, trace and `leads.json` to `.trueup/runs/<run_id>/`. A lead is a disagreement between truth and trace; it is not a confirmed bug.

`audit` runs your script's `main()` against the fake (through `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL`) under the chosen library, once per fake scenario on each provider route the script calls, and compares the same way. It needs a `main()` with no arguments that uses the `openai` or `anthropic` SDK; see `src/trueup/audit.py` for its limits.

`check` runs the checker over a sweep's leads. A lead becomes a finding only if it reproduces twice in fresh processes, on the recommended setup, on the latest release and on the library's main branch, the fake really sent what truth says, the harness is sane, another library or the OpenTelemetry conventions show the right behaviour, and a repro under 40 lines shows it. Otherwise it is withdrawn with the rule that failed (kept and counted). Findings that share a cause are grouped, then searched for in the library's GitHub issues and PRs (read only). It writes `findings.json` and `withdrawn.json` in the run dir.

`plan` asks a model (`claude-sonnet-4.6` through an OpenAI-compatible proxy) for new scenarios, given the library's wrapper source, the scenario library and the latest findings. A proposal is JSON data: an existing app plus an existing fake behaviour, with the truth it expects. Code checks the schema, that the app and fake behaviour exist and fit, that the pair is new, and runs the app untraced to confirm the truth. A rejected proposal goes back to the model with the reason, twice at most. Accepted ones are saved to `scenarios/proposed/<lib>/`; `trueup sweep <lib> --proposed [FROM]` runs them. Before every model call Trueup reads the key's spend from the proxy and stops at $15. It needs `TRUEUP_MODEL_KEY` and `TRUEUP_MODEL_BASE_URL`.

Commands that call the model trace Trueup itself to neatlogs when `NEATLOGS_API_KEY` is set: one session per run (session id = run id), one trace per worker. The scenario runs stay local: their subprocesses get no neatlogs key and have export turned off.

`doctor` also makes one GET each to neatlogs and the model proxy (no model call).

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
uv run trueup plan openllmetry --max 3
uv run trueup sweep openllmetry --proposed
```

## License

MIT. See [LICENSE](LICENSE).
