# Trueup — neatHack business plan

This plan was developed in cfo.ai with Ari and saved there as **“Trueup · neatHack business plan.”** It is based
on the founder-supplied product description and launch status. Proposed customers, packaging, distribution, and
financial assumptions are strategy to validate—not current traction.

## One-line pitch

Trueup makes AI-agent traces trustworthy by detecting incorrect traces, locating the instrumentation bug,
repairing it, and verifying the corrected trace.

## Problem and solution

AI-agent developers rely on traces to understand what their systems did, but instrumentation can record a failed
run as successful or record behavior that differs from execution. Trueup checks trace data against execution
evidence, identifies the instrumentation issue, repairs the recording code, and verifies the corrected trace.

Trueup is positioned as trace correctness, not another monitoring dashboard. Its evidence-backed corrections
complement existing observability products.

## Customers and buying decision

Individual agent developers discover and use the open-source tool. The initial paid customers are engineering
leads and platform teams shipping AI agents whose debugging and release decisions depend on accurate traces.
The key commercial question is whether teams will pay for recurring protection from misleading traces rather
than only a one-time instrumentation repair.

## Product, pricing, and revenue model

- **Free open-source tier:** the core detect → diagnose → repair → verify workflow.
- **Planned team tier:** a monthly subscription for continuous checks on code changes, hosted verification
  evidence, integrations, retention, and team support.
- **Recommended packaging:** a base team subscription with an included check allowance, with explicit limits or
  usage pricing for additional checks, longer evidence retention, and higher support levels.

Trueup has just launched and has no revenue. Final prices are not presented as validated: willingness to pay and
the cost of each code-change check must be measured through design-partner pilots first.

## Costs and unit economics

Delivery costs include verification compute, model usage, evidence storage, integration maintenance, and support.
The evidence bundle currently measures planner/fixer model spend; Trueup should add measured compute and storage
cost per audit before offering unlimited checks. Gross margin should be evaluated per paying team at its included
check allowance.

Measured model cost from Trueup's verified v1/v2 evidence:

| Work | Measured list-price cost | Worker traces opened |
|---|---:|---:|
| Planner v1, two runs | $0.21 | 2 (one per run) |
| Planner v2, two runs | $0.21 | 2 (one per run) |
| OpenInference fixer v1, one run | $0.53 | 6 |
| OpenInference fixer v2, one run | $0.22 | 6 |

The model key's total reported spend after the measured build session was **$7.28**. These are observed build
costs, not proposed customer prices. Compute, storage, support, and repeated team usage still need measurement.

The cfo.ai forecast uses an illustrative **$150,000 starting cash balance**. This is a hypothetical planning input,
not a statement of Trueup's actual cash.

## Revenue and runway scenarios

The cfo.ai live adoption and check-cost simulator connects free-developer adoption to paying teams, subscription
revenue, delivery costs, hiring, and cash. Under its current illustrative assumptions:

- The base case reaches monthly operating break-even in **December 2027**.
- The slower-adoption case exhausts the hypothetical $150,000 starting cash in **January 2028** if the same hiring
  plan is retained.

These dates are scenario outputs, not predictions. The largest modeled cash risk is hiring before team demand is
proven. The operating rule is therefore to validate willingness to pay and cost per check before committing to a
hire, and to revise the forecast with actual cash, spending, active-developer, conversion, and retention data.

## cfo.ai results with measured costs (12 Oct 2026)

cfo.ai's assistant, Ari, updated the plan with Trueup's measured costs ([shared plan](https://cfo.ai/s/kVKIburWzn09Baoy)).
Its first answer counted our own 44 test calls as a cost per customer check; we corrected that, and Ari re-ran the
plan:

- **Per Witness check: $0.** Witness makes no AI calls; it watches the customer's own calls.
- **Checking a tracing-library release:** $0 on the practice AI server, plus about $0.10 (planner) and about $0.52
  per fix needed: $0.10 with no fix, $0.62 with one. At 10 releases a month with one fix each: $6.20 a month.
- **Contribution per team** (price less 3% payment fees and $15 support): $178.03 at $199, $566.03 at $599.
- **Break-even teams:** 38 at $199 and 12 at $599 before the planned engineer hire; 94 and 30 after it
  ($16,608.73 a month fixed spending).
- **Cash, from a hypothetical $150,000 start, October 2026 to September 2028:** at $99 the cash runs out in
  January 2028; at $199 the lowest point is about $31,246 (February 2028); at $599 about $114,386 (July 2027).
- **Ari's recommendation:** test $199 entry pricing and a $599 higher-touch plan with explicit repair allowances,
  and sell continuous assurance, integrations and support rather than AI-call volume.

The starting cash, adoption, hiring and support figures are planning assumptions, not facts about Trueup.

## Go-to-market

Start with developers who have encountered a concrete trace mismatch. Demonstrate reproducible before/after
evidence through the open-source repository, agent-development communities, and integrations. Invite teams that
receive repeated value into design-partner pilots, help them add checks to code changes, and measure repeated use
and willingness to pay. Prioritize paid pilots and retention over download counts.

## Differentiation and defensibility

Trueup closes the loop: identify an inaccurate record, locate the recording defect, repair it, and verify the
correction. Potential defensibility comes from a growing library of instrumentation failure cases, reproducible
verification tests, reliable repair patterns, and workflow integrations. These are advantages to build and
measure, not claims of an established moat.

## Risks and milestones

Key risks are false alarms, unsafe repairs, incomplete verification coverage, sensitive trace data, expensive
checks, and weak recurring value after a one-time fix. Mitigations include reproducible evidence, reviewable
patches, bounded claims, controlled retention, usage allowances, and recurring regression checks.

Next commercial milestones:

1. Demonstrate reproducible mismatches, repairs, and scoped verification evidence.
2. Measure useful detections, false alarms, accepted fixes, and cost per check on real projects.
3. Run team pilots and measure repeated use and willingness to pay.
4. Validate hosted evidence and integration requirements, then finalize pricing and allowances.
5. Convert pilots to subscriptions and measure retention, gross margin, and support demand.

## cfo.ai evidence status

- Shared cfo.ai report containing the workspace artifacts: <https://cfo.ai/s/kVKIburWzn09Baoy>
- Strategy artifact: **“Trueup · neatHack business plan”** — supplied from the cfo.ai workspace.
- Financial artifact: **“Trueup · Launch assumptions”** and its live adoption/check-cost simulator — numerical
  outputs summarized above and available through the shared report.
- cfo.ai account use is real; the forecast's assumptions remain explicitly separate from actual company results.

