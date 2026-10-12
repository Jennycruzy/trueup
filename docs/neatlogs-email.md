# neatlogs' own daily email got the error rate wrong

On 12 October neatlogs sent its automatic daily summary for the Trueup project
(11 Oct 09:00 → 12 Oct 09:00 UTC). It said:

> 81 recorded requests. Recorded errors rose to 6.2%.

We read every one of those 81 runs back from neatlogs (through its MCP server) and checked each against what
really happened. The email's own numbers add up: 81 runs, 5 marked as errors. But 9 of the runs really crashed.

| Test run | How many | What really happened | What neatlogs recorded |
|---|---:|---|---|
| The AI server fails on the second call (`ag-llm-fails`) | 5 | Crashed | Counted as an error, but the top step of every one still says SUCCESS |
| The AI sends an error halfway through its reply (`oa-resp-stream-error-event`) | 4 | Crashed | Success, 0 errors, so not counted at all |
| A normal reply (`an-stream-helper`) | 4 | Fine | Success (correct) |

**The email said 6.2% of runs failed. The real number was 11.1% (9 of 81).** Four crashes never showed up.

## What this does and does not show

- **These were test runs we crashed on purpose.** They came from Trueup's practice AI server (the fake
  provider), not from real customers or a real AI provider. Car safety tests work the same way: you crash the
  car on purpose to see what the instruments report.
- **The tracing code caused it, not the email.** Some runs were recorded by neatlogs' own SDK, the others by
  Arize's OpenInference and Traceloop's OpenLLMetry, all sending into neatlogs. The email added up the records
  it was given; the records were wrong.
- **These were the released versions, without our fixes.** The same failures are Trueup's confirmed findings:
  - neatlogs: [Agents run shown OK](../evidence/findings/neatlogs-run_status-openai-agents-top-level-span-status-ok/finding.json),
    [stream error event left unmarked](../evidence/findings/neatlogs-run_status-openai-responses-stream-top-level-span-status-unset/finding.json)
  - OpenInference: [Agents run shown OK](../evidence/findings/openinference-run_status-openai-agents-top-level-span-status-ok/finding.json)
    (fix under review in [Arize-ai/openinference#4024](https://github.com/Arize-ai/openinference/pull/4024))
  - OpenLLMetry: [Agents run shown OK](../evidence/findings/openllmetry-run_status-openai-agents-top-level-span-status-ok/finding.json),
    [stream error shown OK](../evidence/findings/openllmetry-run_status-openai-responses-stream-top-level-span-status-ok/finding.json)

## The runs, so anyone with access can check

All were sent on 12 Oct 2026 between 01:55 and 02:03 UTC by `trueup demo-export`.

| Library | neatlogs session | Crashed, counted as error (top step SUCCESS) | Crashed, recorded as success | Fine |
|---|---|---|---|---|
| neatlogs | `demo-neatlogs-20261012T015515Z` | `138533163e28239ec9181a42f7a7f899` | `7ecadf2e0debe934e325f0e8814815b2` | `6041090c2877aa7d78861796ee052fcb` |
| OpenInference | `demo-openinference-20261012T015747Z` | `35a7fc38358b72dda5734a3567395c31` | `c874896c638944221ea13d90494c3a56` | `fbcb88f7e7564fb32c76273111c5ceb0` |
| OpenLLMetry | (no session) | `3ba07caf2cd4224bd1d81920f4e398fc` | | |
| OpenLLMetry | `demo-openllmetry-20261012T020143Z` | `83a4fc673acfe9816accd168dd7e5bf2` | `029b630bada8d07d95ca231831a98e18` | `de77ae4cb62008d961f134034ea8c2e1` |
| OpenLLMetry | `demo-openllmetry-20261012T020238Z` | `f2a92448caa40bfe294b9c6f35f85aaa` | `19abad72c41b7c8d480d05d1496c3638` | `fde3d2e15d302506f5f45820e5612df6` |

The other 68 runs in the window are Trueup's own working steps (planner, fixer, checks). neatlogs recorded all of
them as success. They are not test crashes, and we did not check them one by one.

Method: `search_traces` over the window, with several keywords, de-duplicated by trace id (81 found, matching
the email). Then `get_trace_context` for each test run to read its step statuses.
