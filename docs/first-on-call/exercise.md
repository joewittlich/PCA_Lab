# Your first on-call handoff

You are shadowing the person on call for a small web service. They ask, “The slower requests seem to be taking longer. What do we know, and who should we ask for help?” Your job is to give the next responder one observation, one uncertainty, and one check that could change what you do.

Everything you need is on this page. Allow about 15 minutes, or pause between rounds. You can read, listen with a screen reader, speak, or write. The measurements come from a recorded lab run with simulated requests.

- **With a partner:** One person is the responder and the other is the teammate taking the handoff. Read one round at a time. Let the responder think first. Switch roles in round 2.
- **On your own:** Write or say your first response before reading on. In round 2, take the next responder's perspective. For an asynchronous pair, exchange the same short responses in writing.

## Round 1. What changed for someone using the service?

Two checks of the same service estimated its **p95 request time** at about **24 milliseconds**, then about **483 milliseconds**. Each check looked back 30 seconds. P95 means roughly 95 out of 100 requests finished within that time. These are rounded estimates from the service's latency histogram.

1. Give your teammate a one-sentence update in everyday language. What can you say about slower requests? What do you still want to know about people trying to complete a task?
2. The lab also has a detector that learns how measurements usually move together. Predict whether it will flag this change. “I need another measurement” is a reasonable prediction. Say which one and why.

Pause here long enough to record your prediction.

## Round 2. What does the detector add?

The lab uses principal component analysis (PCA) to learn relationships during a **baseline**, an earlier period used for training. Its **score** measures how far a new combination of measurements falls from that learned pattern. A score above **1.102** was flagged in this run. Scores have no time units. The biggest contributor is the measurement that accounted for the largest part of the mismatch.

Here are four selected samples in time order. Times are UTC, with fractional seconds omitted. Scores are rounded.

| Time | Score | Flagged? | Biggest contributor |
| --- | ---: | --- | --- |
| 00:18:33 | 0.363 | No | Fraction of requests that returned errors |
| 00:18:38 | 131.793 | Yes | Average request time |
| 00:18:43 | 117,321.909 | Yes | P95 request time |
| 00:19:13 | 279,907.366 | Yes | P95 request time |

In words, the first displayed sample was below threshold. Five seconds later the score crossed it. Average request time contributed most at the crossing. P95 request time contributed most at the next displayed sample and at the final one.

**Responder:** What would you investigate first? Name one other explanation that could fit. **Teammate:** Ask, “What result from your next check would make you call someone now?” If working alone, answer both prompts. You can ask for help at any point during a first rotation.

## Round 3. Hand it over

Give your teammate a short handoff before opening the reveal. Use these starters if they help.

- “I observed ___, which suggests ___.”
- “I still don't know ___.”
- “I'll ask ___ to check ___. If they find ___, I would ___.”

Then answer a separate question: “Would you wake someone automatically on every future crossing?” Explain your choice. If you need more evidence, name what you would collect.

Now [read the reveal and compare your handoff](facilitator-guide.md#reveal-what-happened). What would you keep, and what would you change?
