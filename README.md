Trueup finds where your AI agent's traces disagree with what really happened, fixes the tracing code, and proves the fix.

## What it does

Teams watch their AI agents through tracing libraries such as neatlogs, OpenInference and OpenLLMetry. These libraries wrap the AI provider's SDK and record each call. When a wrapper gets a case wrong, the dashboard can show a crashed run as OK, miss a refusal, or show twice the real cost.

Trueup runs the agent against a fake provider, so it knows what really happened. It captures what the trace says and compares the two. When they disagree, it looks for the cause in the tracing library, writes a fix with a test, and checks that the fix works.

The work is split into small workers: planner, runner, comparer, checker, deduper, fixer, verifier and reporter. A language model proposes; plain code decides.

## Status: early build

Only the skeleton exists. `trueup doctor` works. The other commands (`audit`, `sweep`, `fix`, `upstream`, `verify`, `report`) print "not built yet" and exit 2.

Exit codes: 0 no mismatches, 1 mismatches found, 2 could not run.

## Run it

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run trueup doctor
uv run pytest -q
```

## License

MIT. See [LICENSE](LICENSE).
