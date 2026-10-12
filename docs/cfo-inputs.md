# cfo.ai inputs — Witness

Every number below comes from a file in this repo.

## Measured costs

- **Live real-traffic cost (MEASURED):** $0.0123794 for 44 real model calls: 40 normal calls (20 before the patches, 20 after) and 4 breaks (2 before, 2 after). Source: `evidence/witness/before.json` key `gate_spend_usd`; call counts from `normal_calls.total`, `normal_calls.after_patches.total` and the `breaks` lists in `before.json` and `after.json`; also `hackathon.md` line 487.
- **Model cost per planner run (MEASURED):** $0.09 to $0.10 per run (proxy figures, which read low); $0.21 at list price for each pair of runs. Source: `hackathon.md` lines 172 and 307–308.
- **Model cost per fix run (MEASURED):** $5.73 over 11 fix runs, about $0.52 per run (`hackathon.md` line 204). Single runs ranged from $0.22 to $0.73 (lines 213–242). The run that produced the proven fix cost $0.40 (line 242).
- **Witness overhead per call (MEASURED):** 2.9005 microseconds median, 4.809 microseconds maximum. Source: `evidence/witness/before.json` key `wrapper_overhead_microseconds`.

## Live demo cost

- **Daily cap:** 300 runs a day (`live/server.py`, `DAILY_CAP`, default `LIVE_DAILY_CAP=300`).
- **ESTIMATE, cost per visitor run:** each run makes one model call (`examples/shop_agent.py`). $0.0123794 ÷ 44 calls = **$0.00028 per run**.
- **ESTIMATE, worst case per day:** 300 runs × $0.00028 = **$0.084 a day**, or about **$2.53 a month** if the cap is reached every day for 30 days.

## Proposed prices (PROPOSAL, no customer has paid)

- **Free (PROPOSAL):** small teams run Witness locally, with a small monthly allowance of traced runs.
- **Team (PROPOSAL):** priced by traced runs per month, with retention, alerts and CI reports. Charge for observed calls, not model tokens.
- **Vendor (PROPOSAL):** for tracing companies. Trueup re-runs its lab on every SDK release and delivers the disagreements it finds, together with tested fixes. A fix costs about $0.52 in model spend (above).

## Questions for Ari (cfo.ai)

1. What is our runway at three Team price levels: low, middle and high per 10,000 traced runs? Include the demo's worst case of $2.53 a month.
2. How many paying customers do we need to break even at each price level, for Team alone and for Team plus one Vendor customer?
3. How does the cost of one audit change with volume? An audit is one planner run plus about $0.52 for each fix run. Show it at 1, 10 and 100 SDK releases a month.
