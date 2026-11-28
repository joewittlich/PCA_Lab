# Facilitating a first on-call handoff

Start learners on the [incident exercise](exercise.md). A successful handoff gives the next person enough evidence to act, including what is still uncertain. No one needs to name the injected fault to complete the exercise.

## Before the reveal

Offer speaking or writing and let the learner set the pace. In a pair, let the person who is newer to on-call interpret the first observation before the experienced partner weighs in. Have them switch roles at the score table. For solo practice, record your first handoff and use the questions below to review it yourself.

- **At the two latency readings**, ask “If you were one of the slower requests, what might you notice?” If the learner says all requests took 483 ms, invite them to explain p95 to a teammate using 100 requests. Give them a chance to revise.
- **At the score table**, ask “Which earlier reading describes the slower requests, and in what units? Can you tell how long any one person waited?” If needed, return to the 100-request example. Then ask for two explanations consistent with slower requests, such as a slow dependency or extra waiting inside the app. Ask what evidence would distinguish them.
- **At the handoff**, play the teammate being asked for help. Ask what to check, over which interval, and what finding would change the response. Let the learner commit to a decision before sharing what the experimenter did.

## Reveal: what happened

The experimenter added 300 ms of latency to the demo app for about 33 seconds while simulated traffic continued, then reset the fault. The model flagged all seven samples labelled as having the latency fault. Those seven observations came from **one slowdown**. A separate 30-second histogram query supplied the rounded p95 readings on the learner page. It used a shorter lookback than the model's one-minute latency inputs.

The saved analysis contains 32 samples taken five seconds apart. Here is how to account for all of them.

| Part of the run | Samples | Flagged |
| --- | ---: | ---: |
| Baseline used to fit the model and threshold | 22 | 1 |
| Held-out normal period used for evaluation | 2 | 0 |
| Labelled latency fault | 7 | 7 |
| Sample immediately after the fault label cleared | 1 | 1 |

The last row in the learner's table is that final sample. The fault label had cleared while recent slow requests were still in the one-minute measurement window. The evaluator allows a short recovery margin and excludes this sample from its held-out normal count. The recording ends there. To establish recovery, ask for newer request measurements. To estimate how often a page would be useful, ask for a longer healthy period and other incidents.

## Compare handoffs

One defensible response is: “The estimate for slower requests rose from about 24 to 483 ms, and request time is contributing most to the alert. I don't know whether an important user task is still slow or failing. I'll ask the service owner to check current completion rates and response times for that task. If it is still impaired, I'll involve the on-call lead now.”

Another responder might involve their on-call partner immediately to help verify impact. Both choices can be reasonable. Invite the learner to explain the evidence and the urgency behind their choice.

For the paging decision, one answer is “I'd keep the score on the dashboard for now. Before using it to wake people, I'd check how often it flags ordinary deployments and whether it catches real customer-impacting slowdowns early enough to help.”

Use these three questions for feedback. Quote a phrase the learner used and invite one revision.

1. **Evidence:** Can the next responder identify a measured change and its units?
2. **Uncertainty:** Did the speaker distinguish a clue about latency from a claim about cause, current recovery, or customer impact?
3. **Action:** Does someone know which check to perform and what result should prompt escalation?

Finish by asking, “You caught one slowdown and saw zero alerts in two held-out normal samples. What else would you want to see before asking a teammate to carry this pager?” A useful answer names a comparison, such as replaying both known incidents and ordinary deployments, and a cost, such as unnecessary overnight pages. In solo practice, revise your handoff, then read it as the person who will receive it.

## Evidence for the facilitator

The [timestamped scores and fault labels](evidence/scores.csv) and [run summary](evidence/summary.json) came from a local Docker Compose run using Prometheus at [revision bf9aaa7](https://github.com/joewittlich/PCA_Lab/tree/bf9aaa7a430050a9a2e5ffa5c50e7652418c8903). The two p95 spot readings and fault duration were observed during that run. The CSV contains model scores and contributor names; the separate p95 query values are reported in the exercise. All evidence needed to complete the lesson is also presented in text above and on the learner page.
