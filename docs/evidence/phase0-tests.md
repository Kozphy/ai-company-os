# Phase 0 execution evidence

2026-10-12, Docker Desktop Linux engine 29.8.0. Read-only source bind, copy into
container `/tmp/repo`, UID/GID 65534, no network, all capabilities dropped,
no-new-privileges, 128 process limit, 768 MiB memory, 1 CPU. No host credentials,
Docker socket, or host execution of upstream code. Existing `evalforge-evalforge`
image used; image is locally available, not a clean dependency installation.

| Repository | Command inside container | Observed result |
|---|---|---|
| EvalForge | `python -m pytest -q tests/test_graders.py tests/test_finance_eval.py tests/test_regression.py tests/test_control_plane_contracts.py` | 22 passed in 0.93s; exit 0 |
| CFO first attempt | `python -m pytest -q tests/test_ci_audit.py tests/test_actions_doctor.py` | exit 1, filename does not exist; corrected to `test_doctor.py` |
| CFO corrected | `python -m pytest -q tests/test_ci_audit.py tests/test_doctor.py` | 36 progress dots were observed; process exit and summary were not captured, so result is UNVERIFIED |
| WNRT | `python -m pytest -q tests/test_observation_not_proof.py tests/test_correlation_not_causation.py tests/test_confidence_not_certainty.py tests/test_policy_not_safety.py` | pending; no pass claim |

An attempted audit dependency image build remains incomplete. A later isolated
CFO container rerun did not return within the tool window; its result remains
UNVERIFIED. The WNRT selected suite has not run. A host uv invocation failed with
`Thread failed to start`; fallback Python 3.12 venv and pip installed application
dependencies successfully. No upstream full-suite / Windows live / provider /
GitHub mutation / cloud tests executed.

Static scanner completed across the three checked-out source trees: CFO 537 files
/ 11 pattern hits, EvalForge 186 / 0, WNRT 2,584 / 20. Output contains relative
paths, line numbers and detector labels, not matched values. Hits require manual
triage; this is not exhaustive secret/history scanning and does not prove absence.
