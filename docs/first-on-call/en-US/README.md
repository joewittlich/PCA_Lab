# Review the first on-call exercise

Start with [Your first on-call handoff](index.html). Download and extract the files before opening the page in a browser. Allow about 15 minutes. A learner can work alone or with a partner. Keep the facilitator guide closed until the learner has given a handoff.

## Follow the evidence

The exercise uses one recorded Prometheus run with simulated traffic. The [score file](../evidence/scores.csv) contains 32 rows in time order. The [summary](../evidence/summary.json) reports 22 training rows, two held-out normal rows, and seven rows during one injected delay. The remaining row came immediately after the delay. The evaluation leaves it out of the normal count to allow for recovery. The two p95 estimates in the first round came from separate 30-second histogram checks. Review the detector scores using the CSV and the fault labels using the same row timestamps.

When reviewing a handoff, ask the learner which measurement changed, what they still need to know about users, and who will check it. Seven flagged samples during the delay describe one event. Only two normal samples were held out. These counts leave the rate of unnecessary pages in ordinary operation uncertain.

## Try a different run

Use the report reader in the lesson to select `scores.csv` or `summary.json` from a local analysis. Select files from the same run if you want to compare them. Importing a report updates the reader. The exercise and facilitator guide continue to use the recorded case so partners can discuss the same evidence.

## Review an edit or translation

US English is the source for the lesson. Keep preferred terms in the [glossary](terminology.json) and keyed messages in the [message catalog](strings.json). The [translation guide](translation-guide.html) explains how to produce and check another language folder. After editing the English page and refreshing the catalog, run `python docs/first-on-call/localize.py --check` from the repository root.

Open the page offline. Use the keyboard to enter a response, reach the guide, and open the reveal. If a change affects a number in the case, compare the time, unit, and fault label with its source before asking a new responder to try it.
