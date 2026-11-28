# Facilitate one PCA prediction exercise

Choose one page. Allow five minutes. With a pair, ask one person to predict the model's decision and the other to name a check for user impact. Working alone, make both decisions before opening the result. Invite the learner to revise one sentence after the reveal.

| Exercise | Ask after the reveal |
|---|---|
| [Same size change, different direction](direction.html) | Traffic reaches a new high and the score stays low. Which user task would you check before saying the service is healthy? |
| [A fault enters the training data](training.html) | Both models saw the same evaluation samples. What happened to healthy flags and to detection of the one replayed fault? |
| [New timestamps, repeated readings](readings.html) | Who can provide a second measurement of incoming traffic? Would that source still work if this collector failed? |

## Reproduce the results

From the repository root, run `uv run python -m sre_pca.prediction_exercises`. The [simulation](../../../src/sre_pca/prediction_exercises.py) uses the existing fixed-seed benchmark. It fits one component on two features and uses the largest training error as its threshold. Its samples are generated separately from the recorded first-on-call handoff.

- The two points are each 2.6 standardized units from the training mean. Moving along the fitted line gives almost zero error. Moving perpendicular to it gives squared error of 6.76.
- The second fit adds 0.28 CPU cores to 24 of 240 training rows. Both evaluation windows stay fixed. Window counts refer to individual samples. The 20 replay samples represent one simulated fault.
- The sensor case copies the first held-out healthy pair at 20 distinct timestamps, 15 seconds apart. Compare the first and last output rows. Scoring compares the two readings in each row with the fitted relationship.

After editing a result, compare the rounded reading, units, and flag with the command output. Run `uv run pytest -q tests/test_prediction_exercises.py` to check the numbers. Open the individual HTML file offline and use the keyboard to write, reveal the result, and save a response. The adjacent [translation guide](translation-guide.html) covers the separate message catalogs.
