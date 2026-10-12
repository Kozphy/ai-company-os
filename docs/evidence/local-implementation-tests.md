# Local application verification evidence

Date: 2026-10-12. Environment: Windows PowerShell, Python 3.12.10, project `.venv`; this is the working venv, not a newly created clean environment.

| Command | Result |
|---|---|
| `.venv/Scripts/python.exe -m pytest -vv tests` | 25 passed in 2.94s; one Starlette/httpx deprecation warning |
| `.venv/Scripts/ruff.exe check company_os migrations tests` | All checks passed |
| `.venv/Scripts/mypy.exe company_os migrations` | Success: no issues found in 14 source files |
| `.venv/Scripts/kozphy.exe --help` | CLI entry point displayed setup, migrate, api, worker, scheduler, demo commands |
| `pip install -e . --no-deps` | Editable package build and install succeeded |
| `pip install -e .audit/ci-failure-orchestrator --no-deps` | Local editable install succeeded from audited checkout commit `f7b6cf2e65b3d2ef3f15cecb4fc1c65874c3f56f` |
| Throwaway `docker compose up --build -d` smoke | API, worker, scheduler, and PostgreSQL built; `/health` returned `ok`, `/ready` returned `true`; test containers, network and named database volume were removed |

Tests cover setup/migration in a temporary directory, auth and tenant boundaries, 1 MB body limit including streamed input without a length header, durable schedule replay, lease fencing/retry, global and tenant kill switches, approval actor/expiry/tamper/replay gates, cost caps, signed webhook dedupe, same-tenant delivery evidence validation, finance truthfulness, secret redaction, and five offline jobs. They do not simulate a killed process or real PostgreSQL fault.

The separately declared GitHub VCS dependency points to the same immutable CFO revision; the local editable install used the already-audited checkout to avoid downloading source again. No test contacted GitHub or invoked upstream patch execution. The committed CI workflow and cloud deployment were not executed; the Compose test was local only.
