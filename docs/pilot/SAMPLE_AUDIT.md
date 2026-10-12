# Sample CI Reliability Audit (synthetic demonstration)

> DEMO ONLY. Repository, runs, and failures below are fabricated test fixtures. This is not a customer report, verified audit, or assurance certification.

## Scope

Illustrative 30-day analysis window for `demo/sample`, based on one caller-supplied fixture. No GitHub API fetch or log retrieval occurred.

## Findings

- Completed runs in fixture: 1
- Failed runs: 1
- Failure rate: 100% for this one-run synthetic sample
- Failure classification: UNKNOWN; event metadata has no job logs or step output
- Evidence source: offline export fixture; origin was not independently authenticated

## Recommended next steps

1. Confirm the export covers the agreed repository and window.
2. Provide authorized read access or a reproducible export with job and step evidence.
3. Classify failures with supporting logs and link each finding to a run.
4. Have an engineer review recommendations before applying changes.

## Limitations and sign-off

This report provides engineering observations only. It does not certify security, availability, compliance, or future CI success. No patches were applied. Human review is required before delivery.
