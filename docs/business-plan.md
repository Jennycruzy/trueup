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

- Shared cfo.ai report containing the workspace artifacts: <https://cfo.ai/s/a9JKll8UYmSHs7-F>
- Strategy artifact: **“Trueup · neatHack business plan”** — supplied from the cfo.ai workspace.
- Financial artifact: **“Trueup · Launch assumptions”** and its live adoption/check-cost simulator — numerical
  outputs summarized above and available through the shared report.
- cfo.ai account use is real; the forecast's assumptions remain explicitly separate from actual company results.

