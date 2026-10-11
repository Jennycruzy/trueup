Trueup finds where your AI agent's traces disagree with what really happened, fixes the tracing code, and proves the fix.

Demo video (coming 12 Oct) · [Evidence page](docs/index.html) · [Verify it yourself](#run-it) · [Technical report](hackathon.md)

[![CI](https://github.com/Jennycruzy/trueup/actions/workflows/ci.yml/badge.svg)](https://github.com/Jennycruzy/trueup/actions/workflows/ci.yml)

The [neatHack business plan](docs/business-plan.md) documents the free-to-paid product strategy, target customer,
risks, measured model costs, and validation milestones. Its [cfo.ai workspace](https://cfo.ai/s/a9JKll8UYmSHs7-F)
keeps illustrative prices and forecasts separate from launch-stage facts.

## What it does

Teams watch their AI agents through tracing libraries such as neatlogs, OpenInference and OpenLLMetry. These libraries wrap the AI provider's SDK and record each call. When a wrapper gets a case wrong, the dashboard can show a crashed run as OK, miss a refusal, or show twice the real cost.

Trueup runs the agent against a fake provider, so it knows what really happened. It captures what the trace says and compares the two. When they disagree, it looks for the cause in the tracing library, writes a fix with a test, and checks that the fix works.

The work is split into small workers: planner, runner, comparer, checker, deduper, fixer, verifier and reporter. A language model proposes; plain code decides.

## Verified result

`trueup verify` currently recomputes this headline from the committed evidence:

| Library | Confirmed findings | High | Medium |
|---|---:|---:|---:|
| neatlogs | 17 | 6 | 11 |
| OpenInference | 6 | 3 | 3 |
| OpenLLMetry | 9 | 6 | 3 |
| **Total** | **32** | **15** | **17** |

Three patches are proven against their target cases, package suites, and the full 57-scenario library, with zero
new mismatches. Five findings match an existing upstream issue or pull request. A “finding” here means every
checker rule passed; leads that failed or could not complete a rule remain visible separately.

### One finding, start to finish

An OpenAI Agents run raised an error, but OpenInference ended its top-level `Agent workflow` span as OK. Trueup
reproduced that disagreement twice, checked the latest release and main branch, verified the fake and harness,
compared the OpenTelemetry rule, and ran a 30-line repro. The first drafted patch incorrectly turned a recovered
tool error into a failed run; the full scenario sweep rejected it. The second draft passed: 5 affected scenarios
changed from OK to ERROR, the package suite went from 295 to 298 passing tests, and the full-library lead count
fell from 19 to 14 with no new mismatch. See the [before/after proof](fixes/openinference-run_status-openai-agents-top-level-span-status-ok/before-after.md)
and [failed-then-passed Neatlogs traces](docs/neatlogs.md).

### Proven repair cards

| Finding | Before → after | Proof |
|---|---|---|
| OpenInference failed agent root shown OK | 5 affected scenarios corrected | [proof](fixes/openinference-run_status-openai-agents-top-level-span-status-ok/summary.md) |
| OpenLLMetry duplicate Agents LLM spans | `ag-run` 4 → 2 spans for 2 calls | [proof](fixes/openllmetry-call_count-openai-agents-llm-spans-wrong/summary.md) |
| neatlogs failed `messages.stream()` shown OK | 2 affected scenarios corrected | [proof](fixes/neatlogs-run_status-anthropic-messages-stream-top-level-span-status-ok/summary.md) |

### Guarantees and boundaries

| Guarantee | Implementation | Test or evidence |
|---|---|---|
| Model output cannot confirm a finding | `src/trueup/core/checker.py` | `tests/test_checker.py` |
| A patch must fail before and pass after | `src/trueup/fixer/verify.py` | `tests/test_fixer.py`; each `proof.json` |
| Full-library regressions reject a patch | `src/trueup/fix.py` | all 3 fixed findings report 0 new mismatches |
| Evidence numbers and bytes are reproducible | `src/trueup/evidence.py` | `uv run trueup verify` |
| Scenario children cannot export user traces | `src/trueup/runner/run.py` | `test_inner_spans_never_leave_the_machine` |

Real: controlled fake-provider truth, 32 checked findings, 3 locally proven patches, read-back Neatlogs evidence,
and three upstream drafts. Partial: provider recording supports opted-in OpenAI/Anthropic calls, but no real provider
key was supplied for the final cross-check. Not claimed: universal agent correctness, safe automatic merging,
upstream acceptance, customer traction, or public deployment of the report/video.

Entire checkpoint explanations for the six build stages are saved in
[`evidence/entire/checkpoints.json`](evidence/entire/checkpoints.json). Per-fix graph evidence is beside each fixed
finding. Across the three proven patches, the graph ranked a patched function first in 0 of 3 cases; it ranked an
OpenInference patched function second, found an OpenLLMetry patched function sixth, and missed the neatlogs wrapper.

### Upstream status

| Finding | Issue | PR | Status |
|---|---|---|---|
| OpenInference root status | draft only | draft only | waiting for owner approval |
| OpenLLMetry duplicate spans | [possible duplicate #4377](https://github.com/traceloop/openllmetry/pull/4377) | draft only | re-check before posting |
| neatlogs stream status | draft only | draft only | waiting for owner approval |

## Status: working vertical slice

`trueup doctor`, `trueup demo`, `trueup bundle`, `trueup verify`, `trueup report`, `trueup evidence pull`,
`trueup traces <session-id>`, `trueup sweep <neatlogs|openinference|openllmetry>`,
`trueup audit <script> --library <lib>`, `trueup check <run_id|latest> --library <lib>`,
`trueup plan <lib> [--max N]`, `trueup fix <finding-id>` and `trueup upstream <finding-id>` work.

The judge-facing proof is available in the [static evidence report](docs/index.html). `trueup demo` replays one complete verified finding locally; it needs no API keys, network access or model call. `trueup verify` recomputes the report's numbers and checks every evidence hash.

`bundle` writes `evidence/` from the local runs, fixes and upstream drafts. `verify` needs only `evidence/`: no keys, no network; it fails if any byte changed. `report` builds `docs/index.html` from a bundle that verifies. `traces <session-id>` reads a run's own traces back from neatlogs through its MCP server. `fix <id> --reprove` re-applies a committed patch and sweeps every scenario again (no model call). `plan` and `fix` take `--variant v1|v2`; the comparison is in `hackathon.md`.

In CI: `uses: Jennycruzy/trueup@main` with `script` and `library` inputs runs `trueup audit` (see `action.yml`). As an Entire plugin: `entire-trueup` is installed with the package, so `entire trueup verify` works when it is on PATH.

`sweep` runs the scenarios (plain SDK, LangChain/LangGraph and the OpenAI Agents SDK; pick with `--framework`) against a fake provider, compares truth with the trace, prints a table of leads and writes truth, trace and `leads.json` to `.trueup/runs/<run_id>/`. A lead is a disagreement between truth and trace; it is not a confirmed bug.

`audit` runs your script's `main()` against the fake (through `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL`) under the chosen library, once per fake scenario on each provider route the script calls, and compares the same way. It needs a `main()` with no arguments that uses the `openai` or `anthropic` SDK; see `src/trueup/audit.py` for its limits.

`check` runs the checker over a sweep's leads. A lead becomes a finding only if it reproduces twice in fresh processes, on the recommended setup, on the latest release and on the library's main branch, the fake really sent what truth says, the harness is sane, another library or the OpenTelemetry conventions show the right behaviour, and a repro under 40 lines shows it. Otherwise it is withdrawn with the rule that failed (kept and counted). Findings that share a cause are grouped, then searched for in the library's GitHub issues and PRs (read only). It writes `findings.json` and `withdrawn.json` in the run dir.

`plan` asks a model (`claude-sonnet-4.6` through an OpenAI-compatible proxy) for new scenarios, given the library's wrapper source, the scenario library and the latest findings. A proposal is JSON data: an existing app plus an existing fake behaviour, with the truth it expects. Code checks the schema, that the app and fake behaviour exist and fit, that the pair is new, and runs the app untraced to confirm the truth. A rejected proposal goes back to the model with the reason, twice at most. Accepted ones are saved to `scenarios/proposed/<lib>/`; `trueup sweep <lib> --proposed [FROM]` runs them. Before every model call Trueup reads the key's spend from the proxy and stops at $15. It needs `TRUEUP_MODEL_KEY` and `TRUEUP_MODEL_BASE_URL`.

`fix` works on one finding. It shallow-clones the library into `.trueup/clones/<lib>` and finds the wrapper and its callers (Entire's code graph first: `entire graph search`, `neighbors` and `impact`; ripgrep and Python's ast only as the fallback, and `locate.json` says which and why; `--locate-only` re-runs just this step and compares it with the verified patch). The model drafts the smallest change and a unit test in the package's own style; code applies it to the clone. A try is kept only if the new test fails before and passes after, the package's own test suite shows no new failure, the finding's scenarios now match truth, and the full scenario library (run in `.trueup/venvs/<lib>-fix` with the patched package) has no new mismatch. A failed try goes back to the model with the reason, 3 tries at most; then the finding stays unfixed and says so. It writes `fixes/<finding-id>/`: `patch.diff`, the test file, `before-after.md`, `suites.json`, `locate.json`, `tries.json`, `summary.md`, and every run's tries in `runs/`. Exit 0 fixed, 1 not fixed, 2 could not run. Fixes exist for three findings; see `fixes/`.

`upstream` drafts `issue.md` and `pr.md` into `upstream/<finding-id>/`, following the library's issue and PR templates. The text says what goes wrong, which cases are affected and which are not, the before/after table and the environment. It includes a repro under 40 lines that needs only the library and the provider SDK. The repro is run on the latest release and on the patched clone, and both outputs go into the text. Nothing is posted.

Commands trace Trueup itself to neatlogs when `NEATLOGS_API_KEY` is set: one session per run (session id = run id),
one trace per worker, with workflow, library, command, run, and v1/v2 tags. Trueup flushes and shuts down the SDK
before exit. `trueup evidence pull` reads detections, trends, analytics, and fix suggestions through Neatlogs MCP.
`audit --neatlogs` adds one `Trueup mismatch` child span per mismatch and enables the SDK's PII redaction.

Scenario subprocesses deliberately send nothing to Neatlogs. This protects user prompts and code and avoids using
the project's span allowance for the trace data Trueup is testing; children receive no key and have export off.

Planner and fixer system prompts are managed in Neatlogs under versioned names with label `production`.
Exact offline copies and hashes live in [`prompts/`](prompts/), so the judge path needs no Neatlogs account.

`doctor` also makes one GET each to neatlogs and the model proxy (no model call).

### Neatlogs features used and not used

Used: Python SDK traces, worker attributes, v1/v2 tags, detections, failure-run evidence, managed prompts, MCP
trace/detection/analytics/fix reads, and opt-in PII-redacted audit mismatch spans. The machine-readable pull is in
`evidence/neatlogs/` after `trueup bundle`; the [failure links and exact dashboard hand-back](docs/neatlogs.md)
are kept together.

Dashboard hand-back: the owner still needs to create the AI evaluation and alert, add comments, and capture the
workflow/tag/prompt-history screenshots. The evaluation question is: “Is every confirmed finding backed by all
seven passing checker rules and a runnable reproduction?” Score 1 only when both are present; otherwise 0. It is
advisory and never changes Trueup's code verdict. Alert on `Trueup: lead withdrawn (own false alarm)` with one hit
in 15 minutes. A service-account Public API credential was not supplied; the ingest key correctly returned 401,
so read evidence uses MCP instead.

Not used, with reason:

- TypeScript, Go, and browser SDKs: Trueup's command line and test harness are Python.
- HTTP injection and direct OTLP: the supported SDK exporter already owns delivery.
- Imported traces: Trueup compares traces captured during its own controlled runs.
- End-user identity and secondary clients: Trueup has build runs, not product end users.
- Fix dispatch: patches remain reviewable local drafts; no Cursor or cloud agent is authorized to apply them.
- Distributed scenario tracing: disabled for privacy and span allowance as described above.
- Neatlogs plugin: not installed because it records broadly without Trueup's child-process redaction boundary on a
  shared machine.
- neatroots: used only as visual evidence of the original crashed-run-shown-OK problem, not as a runtime dependency.
- Crustdata: Trueup checks tracing code; it needs no company or people data.

Exit codes: 0 no leads, 1 leads found, 2 could not run.

## Run it

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run trueup doctor
uv run trueup demo             # offline before/after proof for the featured fix
uv run trueup verify           # recompute and validate the committed evidence
uv run trueup report           # rebuild docs/index.html
uv run trueup evidence pull    # authenticated, read-only Neatlogs evidence
uv run pytest -q               # offline unit tests
uv run trueup sweep openllmetry --case ag-run   # the double-span case
uv run pytest -q -m e2e  # builds per-library venvs, runs subprocesses
uv run trueup sweep neatlogs
uv run trueup sweep openllmetry --framework openai-agents
uv run trueup audit examples/agent.py --library openinference
uv run trueup audit examples/agent.py --library openinference --neatlogs
uv run trueup check latest --library neatlogs
uv run trueup plan openllmetry --max 3
uv run trueup sweep openllmetry --proposed
uv run trueup fix openllmetry-call_count-openai-agents-llm-spans-wrong
uv run trueup upstream openllmetry-call_count-openai-agents-llm-spans-wrong
```

`audit --cases mine` loads `.trueup/cases/*.json`. Each reviewed data file has exactly an `id`, a provider
`route` (`/v1/chat/completions`, `/v1/responses`, or `/v1/messages`), and a `scenario` supported by that route.
It combines existing fake wire behaviors with the user's agent; custom executable code is never loaded.

## Building in public

Posts on X during the event (#neatHack):

- 11 Oct: Trueup flags its own mistakes in neatlogs: https://x.com/jennyoliver57/status/2109360422029594753

## License

MIT. See [LICENSE](LICENSE).
