# Judging

## Assignment and isolation

Organizers assign existing accounts to events. Review reads and writes are authorized by the backend against the judge's own account and event assignment. A judge may read their own scores; a request naming another judge is rejected with `403`. Participant identities are rejected from judge-score endpoints.

## Weighted rubric

Each criterion has an organizer-configured integer weight, and the UI requires the weights to total 100. Judges score each criterion from 1 to 5. A judge's raw project score is:

`raw = sum(weight_i * score_i / 5)`

## Cross-judge normalization

For each judge, the service computes the mean and population standard deviation of that judge's raw scores across their reviewed projects. For a non-flat distribution, a score is transformed as `50 + 15 * (raw - mean) / standard_deviation`, clipped to the 0-100 range. A judge with zero score deviation retains their raw scores because z-score normalization is undefined for that distribution. A project's normalized score is the mean of its available normalized judge scores, rounded to an integer.

This avoids treating a consistently harsh or generous judge's raw scale as directly comparable to other judges. It does not invent missing reviews: projects use the judges' completed scores only. Participants see scores and comments only after the organizer publishes results.

## Known limits

The current scoring workflow uses event-level rubric criteria and does not yet provide a full audit log or pairwise judging mode. The fixture acceptance report checks judge isolation and CSV export; it does not prove the statistical quality of normalization.