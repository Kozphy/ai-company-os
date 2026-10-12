# Local application verification evidence

Date: 2026-10-12. Environment: Windows PowerShell, Python 3.12.10, project `.venv`; this is the working venv, not a newly created clean environment.

| Command | Result |
|---|---|
| `.venv/Scripts/python.exe -m pytest -q tests` | 32 passed; one Starlette/httpx deprecation warning |
| `.venv/Scripts/ruff.exe check company_os migrations tests` | All checks passed |
| `.venv/Scripts/mypy.exe company_os migrations` | Success: no issues found in 17 source files |
| `.venv/Scripts/kozphy.exe --help` | CLI entry point displayed setup, migrate, api, worker, scheduler, demo commands |
| `pip install -e . --no-deps` | Editable package build and install succeeded |
| `pip install -e .audit/ci-failure-orchestrator --no-deps` | Local editable install succeeded from audited checkout commit `f7b6cf2e65b3d2ef3f15cecb4fc1c65874c3f56f` |
| Throwaway `docker compose -p kozphy-auth-smoke up --build -d` smoke | Current API, worker, scheduler, and PostgreSQL built; API ran migrations through authorization schema revision 0002; `/health` returned `ok`, `/ready` returned ready; test containers, network and named database volume were removed |

Tests cover setup/migration in a temporary directory including upgrade from 0001 to 0002, operator-recorded customer authorization scope and lifetime, expiry and revocation denial, tenant auth boundaries, EvalForge JSON import revision/shape validation, tenant isolation and idempotency, supplementary-only state, research URL canonicalization, source deduplication and explicit unverified publication-date states, 1 MB body limit including streamed input without a length header, durable schedule replay, lease fencing/retry, global and tenant kill switches, approval actor/expiry/tamper/replay gates, cost caps, signed webhook dedupe, same-tenant delivery evidence validation, finance truthfulness, CI gate recommendation policy, secret redaction, and five offline jobs. They do not simulate a killed process or real PostgreSQL fault.

The separately declared GitHub VCS dependency points to the same immutable CFO revision; the local editable install used the already-audited checkout to avoid downloading source again. No test contacted GitHub or invoked upstream patch execution. The committed CI workflow and cloud deployment were not executed; the Compose test was local only.
