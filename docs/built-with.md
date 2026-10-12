# Built with neatlogs, Entire and cfo.ai

## neatlogs

**Recording.** neatlogs records every run of the agent Witness watches, and every run of Trueup's own agent
(planner, checker, fixer, verifier), each as one record with its steps.

**Witness's step lives in the same record.** When Witness finds a disagreement, its red `TRACE DISAGREE` step is
added next to the step that is wrong, so you see the claim and the correction together. See the before and after
records in [witness-before-after.md](witness-before-after.md).

**Detections.** Trueup installs a neatlogs detection group, `Trace truth (by Trueup)`, that flags AI steps marked
SUCCESS with no output, and AI steps with no output or no token count. In the pull of 12 Oct, 10:03 UTC
(`evidence/neatlogs/detections.json`, 30-day window), "LLM output was not recorded" and "LLM succeeded without
output" had 30 hits each, and "LLM token count was not recorded" 14. Rules that need several steps at once ship
as code in `detections/` (`crashed_run_ok.py`, `duplicate_llm_calls.py`). Details: [detections.md](detections.md).

### neatlogs caught problems in Trueup's own agent

Trueup's agent marks its own trouble as named steps, and neatlogs detections match them. Counts are from the same
pull (30-day window).

| Detection | Hits | What it caught | How it was resolved |
|---|---:|---|---|
| Trueup: model reply was not JSON | 31 (26 on 11 Oct, 5 on 12 Oct) | Replies that opened with prose. In the first version 14 of 40 fixer calls were not JSON, and each was retried with the full ~25k-token prompt. | First, Trueup took the first JSON object in the reply. Then it asked the model for JSON replies: two planner runs used 4 calls and one fixer run used 3, with no JSON retry. |
| Trueup: lead withdrawn (own false alarm) | 2 (11 Oct) | The OpenLLMetry check `20261011T180637Z-openllmetry` set aside two possible problems. | Both failed the "latest release and main" rule: already fixed on main. Kept in `withdrawn.json`, not reported as findings. |
| Trueup: fix attempt failed (retried) | 13 (6 on 11 Oct, 7 on 12 Oct) | Fixer tries that did not apply or failed the verifier. | Each failed try went back to the model with the reason. A run whose three tries all failed reported `fixed: false` and replaced no proven fix. |
| Trueup: command could not run (exit 2) | 0 | A Trueup command that could not start. | Nothing to resolve: no hits in the window. |

**27 false alarms of Trueup's own, removed.** Trueup's comparison once expected a finish reason on agent
framework steps where none applies. Comparing the same saved run again with the corrected comparison went from
58 possible problems to 31; all 27 removed ones were of this kind. They stay listed in `withdrawn.json`.

### The model key from neatlogs

neatlogs gave every team at the event a model key: a LiteLLM endpoint (an address that speaks the OpenAI format
and forwards to Claude and other models). Every real call in the live result used it. All 44 live calls (40
normal, 4 breaks) cost $0.0123794.

### neatlogs' own email

neatlogs' daily email said 6.2% of Trueup's runs failed. We checked all 81: 9 had really crashed, 11.1%. The email
added up correctly; the tracing code had recorded crashes as success. These were test runs we crashed on purpose.
[Every run](neatlogs-email.md).

## Entire

**Every fix links to the session that made it.** Each `fixes/<id>/PROVENANCE.md` names the commit that first added
the fix, its Entire record, and the fixer's tries with their cost. Three of the five fixes have an Entire record;
the other two say plainly that their commit has none (see below). Example: the OpenInference fix came from
checkpoint `01M4M8M1GSQ2BM1RX2JKDJHPD6`,
[commit 79210a4 on Entire](https://entire.io/gh/Jennycruzy/trueup/commit/79210a45418246ceb95e2990d1c003b5fbc7b3d9).
All records: [entire.io/gh/Jennycruzy/trueup](https://entire.io/gh/Jennycruzy/trueup).

**Code graph.** To find the code at fault, `src/trueup/fixer/locate.py` first asks Entire's code graph, with the
finding as a sentence, then its callers and impact. The honest result for the three fixes measured: the graph
ranked the patched function 2nd for OpenInference, 6th for OpenLLMetry, and missed it for neatlogs. The fix runs
themselves used the fallback (ripgrep and Python's own parser on functions named by hand).

**What Entire did not record.** Entire recorded the build of Trueup's core: 10 commits from `dadba2f` to
`88fcc91`. The 20 commits from `56d705d` to `6ea4eee` were made in sessions started outside this folder, so they
have no Entire record. We did not create records afterwards. From 12 Oct, about 14:35 UTC, all work is recorded
again. Details in the [build log](../hackathon.md).

## cfo.ai

The business plan, with runway and break-even questions, is on cfo.ai:
[https://cfo.ai/s/kVKIburWzn09Baoy](https://cfo.ai/s/kVKIburWzn09Baoy). The inputs are in [cfo-inputs.md](cfo-inputs.md).

**Measured costs**

- Live real calls: $0.0123794 for 44 calls (40 normal, 4 breaks).
- Planner: $0.09 to $0.10 per run.
- Fixer: $5.73 over 11 runs, about $0.52 per run; the run that produced the proven fix cost $0.40.
- Witness's added time: 2.9005 microseconds per call at the median, 4.809 at most.

**Estimates**

- Live demo: $0.00028 per visitor run; at most $0.084 a day, about $2.53 a month at the 300-run daily cap.

**Proposals (no customer has paid)**

- Free: run Witness locally, with a small monthly allowance.
- Team: priced by recorded runs per month, with history, alerts and CI reports.
- Vendor: for tracing companies. Trueup re-runs its lab on every release and delivers what it finds, with tested
  fixes.
