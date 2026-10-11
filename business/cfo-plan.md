# Trueup — neatHack business plan

## One-line pitch

Trueup makes AI-agent traces trustworthy by detecting incorrect traces, locating the instrumentation bug, repairing it, and verifying the corrected trace.

## Problem

AI-agent developers rely on traces to understand what their systems did. But the code that records those traces can be wrong: a failed run can appear successful, or the recorded execution can differ from what actually happened. A polished monitoring dashboard is not enough if the underlying record is inaccurate. Teams can waste time investigating the wrong cause or ship changes based on misleading evidence.

## Solution

Trueup is an open-source developer tool built around a detect → diagnose → repair → verify workflow. It checks recorded traces against execution evidence, identifies the instrumentation issue responsible for a mismatch, repairs the recording code, and verifies the corrected trace against the checks performed.

The proposed positioning is trace correctness, not another monitoring dashboard. Trueup's value is an evidence-backed correction to the recording layer. Verification claims should state the tested scope rather than imply that every agent behavior has been proven correct.

## Customers and buying decision

The initial target is development teams building and shipping AI agents, especially teams whose agents use multiple tools or execution paths and whose debugging depends on traces. Individual developers are the users who discover and try the product. Engineering leads and platform teams are the likely buyers when trace correctness becomes a shared release requirement.

The commercial question to validate is whether teams will pay for ongoing protection against misleading traces—not merely for a one-time instrumentation fix.

## Product and revenue model

**Free, open-source tier:** individual developers can use the core detect, diagnose, repair and verify workflow. Its role is to demonstrate value, build trust and encourage adoption.

**Planned paid team tier:** a monthly subscription adds continuous checks on code changes, hosted verification evidence, integrations and team support. Teams pay for repeated verification and shared operational workflows, rather than access to the core repair capability alone.

Recommended packaging: a base team subscription with an included check allowance and explicit limits for higher usage, evidence retention and support. This keeps entry pricing understandable while protecting margins if verification becomes expensive. Final pricing requires customer and cost validation; no price is claimed as established.

## Go-to-market

Start with developers who have encountered a concrete trace mismatch. Use reproducible examples and before-and-after evidence to demonstrate the problem and the fix. Distribute through the open-source repository, agent-development communities and integrations with the tools those developers already use.

Invite teams that get value from the free tool into design-partner pilots. Help them add checks to their code-change workflow, then test whether they continue using the product and will pay for hosted evidence, integrations and support. Prioritize repeat use and paid pilots over GitHub attention alone.

## Differentiation

The intended distinction from tracing and evaluation tools is the closed loop: identify an inaccurate record, find the recording bug, repair it and verify the correction. The aim is to complement existing observability tools rather than require teams to replace their monitoring stack.

Potential defensibility comes from a growing library of instrumentation failure cases, reproducible verification tests, reliable repair patterns and integrations embedded in team workflows. These are advantages to build and demonstrate, not a claim of an established moat.

## Economics and risks

Revenue depends on paying teams, subscription price, retention and usage. Delivery costs include verification compute, evidence storage, integration maintenance and support. Measure cost per check and per paying team before offering unlimited continuous verification.

Key risks are false alarms, unsafe repairs, incomplete verification coverage, sensitive code or trace data, expensive checks and weak reasons to pay after a one-time fix. Mitigations to validate include reproducible evidence, reviewable changes and rollback, explicit supported scope, controlled retention and access, usage allowances, and recurring checks that catch regressions.

## Current stage and next milestones

Trueup has just launched and has no revenue, according to the founder. The paid team offering is planned. Customer counts, retention, willingness to pay and unit costs have not been supplied or verified.

Next milestones:

- Demonstrate reproducible trace mismatches, instrumentation repairs and scoped verification evidence.
- Observe developers using the free workflow on real projects; measure useful detections, false alarms and accepted fixes.
- Run team pilots with checks on code changes; measure repeated use and willingness to pay.
- Validate hosted evidence and integration requirements, then cost and package the paid tier.
- Convert pilots into paid subscriptions and measure retention, gross margin and support demand.

## Submission summary

Trueup is an open-source developer tool that makes AI-agent traces trustworthy. It detects when a trace misrepresents execution, identifies the instrumentation bug, repairs it and verifies the corrected trace. The free tier earns developer trust through an evidence-backed fix. The planned paid tier turns that one-time value into continuous protection: checks on code changes, hosted evidence, integrations and team support. Trueup has just launched with no revenue; the next commercial milestone is to validate recurring team usage and convert pilots into paid subscriptions.

## Basis and assumptions

This plan is based on the founder-supplied product description and launch status. Customer targets, packaging, distribution and milestones are proposed strategy. No neatHack-specific submission rubric was supplied. The separate financial forecast contains illustrative assumptions and is not presented here as traction or a validated business forecast.
