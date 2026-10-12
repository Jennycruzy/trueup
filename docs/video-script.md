# Trueup Witness video — 2:30

## 0:00–0:12

Draw two cockpit instruments and a red DISAGREE panel. No crash footage.

“Planes compare independent instruments. On the 737 MAX, an AOA DISAGREE alert intended to warn when two readings differed did not work on most aircraft. Your AI agent flies on one instrument: its trace.”

## Line to use (neatlogs' own email), about 10 seconds, after 0:55 or as the opening hook

Show the real neatlogs daily email ("Recorded errors rose to 6.2%"), then the count.

“neatlogs' own daily email said 6.2% of our runs failed. We checked all 81. Nine had crashed: 11.1%. These were test runs we crashed on purpose, recorded by the tracing tools as anyone downloads them today. The tracing code missed four crashes. The email only added up what it was given.”

Must stay in: crashed on purpose, not real customers; released versions without our fixes; the tracing code caused it, not the email. Say "the tracing code", not "neatlogs' code" (Arize's and Traceloop's tools recorded some of the runs).

## 0:12–0:35

Run the shop agent through the local cable-cut relay. Show the real provider response begin, then the application exception beside neatlogs' successful trace.

“We cut the cable during a real Claude Haiku stream. The app crashed. The trace said success.”

## 0:35–0:55

Show `TRACE DISAGREE` inside trace `5322259c536eae9651b3f0819bfade85` (the AI step says SUCCESS right above it), then the detection.

“Witness watches the wire independently. It writes the disagreement into that same neatlogs trace. The detection fires.”

## 0:55–1:30

Show the proposed patches (the three neatlogs patches, then Arize PR #4024 with the maintainer's review), then rerun both breaks and open the two after traces: `7304699be40a6194bafc2a45478bcd4f` (cut, AI step ERROR) and `83f710d188f00e206a8b2339e0560443` (agent, workflow ERROR).

“Trueup found the cause. For the cut stream it was in neatlogs' own code. For the agent run it was in Arize's code, which neatlogs uses underneath, so we sent the fix to Arize, and their maintainer reviewed it. Same breaks, run again: both records now say the run failed. The light goes out: two before, zero after. Our first try did not get there, and we kept that record.”

## 1:30–1:50

Show the two-line install, `TRUEUP_WITNESS=0`, and the normal-call sessions (`witness-normal-before-1212`, `witness-normal-after-1212`).

“Add the second sensor in two lines. It never changes the app's result. Forty normal real calls, zero false alarms.”

## 1:50–2:20

Show the offline lab: 32 findings, five proven patches, upstream links and Entire records. Open the cfo.ai plan.

“The offline lab explains how we found the failures: 32 checked findings and five locally proven patches across three tracing libraries. Entire keeps the repair record. cfo.ai holds the volume-priced plan.”

## 2:20–2:30

Return to the red panel.

“Your dashboard said OK. Your agent crashed. Trueup turns on the DISAGREE light.”
