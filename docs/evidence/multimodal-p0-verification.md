# P0 Verification Record — 2026-11-12 (Asia/Taipei)

## Source inspection
Inspected default-branch file trees plus key implementation files in three repositories:
- RepoRevenue: `README.md`, `src/lib/store.tsx` (mock browser data, timeout-based post creation).
- ai-company-os: `README.md`, `pyproject.toml`, `company_os/agents.py`, `company_os/jobs.py`, `tests/test_jobs_agents.py`, `.github/workflows/ci.yml`.
- EvalForge: `README.md`, `finance_eval/evidence.py` (SHA-256 / evidence conventions).

## New branch
`feat/multimodal-gtm-p0`, based on `pr/02-local-mvp`, the repository default branch at the time of review. No merge or deployment.

## Tests / evidence status
- Added a real encoding integration test. It creates a PNG and a WAV using FFmpeg test sources, calls the renderer, checks for an MP4 file containing an `ftyp` atom, checks required streams, duration/dimensions and independently recomputes the SHA-256.
- Added defensive tests for path traversal, symlink input, unsupported manifest fields, invalid dimensions, missing audio and overwrite.
- **Execution status: NOT VERIFIED PASSING.** GitHub Actions runs on branch showed failure; the pre-change baseline run was also failing. No reliable failure logs or step details were obtainable through the connected GitHub API. Do not infer P0 passed or that all CI failures came from P0.
- Baseline workflow: https://github.com/Kozphy/ai-company-os/actions/runs/43065338976
- P0 workflow after initial code/tests: https://github.com/Kozphy/ai-company-os/actions/runs/43065564362
- Locally verified only that the available FFmpeg executable can emit a synthetic PNG and WAV; not a full checkout run of this branch.

## Required before merge
1. Run `ruff check company_os migrations tests` and `pytest -q` with FFmpeg/FFprobe (including x264/AAC encoding) installed.
2. Investigate CI failure from job logs; rerun for Python 3.11 and 3.12.
3. Review file path / output race conditions and resource limits; treat output folder as operator-controlled.
4. Independently reproduce a real media render and verify `evidence.json` hashes and duration.
5. Keep publication disabled and obtain human review; deployment is explicitly out of scope.
