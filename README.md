# Kozia AI Company OS

Local, evidence-first solo-operator MVP. Workflows are deterministic offline demonstrations and imported-export analysis. No live model, autonomous GitHub mutation, customer, paid pilot, or cloud deployment is configured.

## Local run

Requires Python 3.11+ (tested locally with Python 3.12).

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\kozphy setup
.venv\Scripts\kozphy api
```

Open `http://127.0.0.1:8000/`. `setup` generates a local operator token and prints it once. Store it securely; `.env` is ignored by Git. API docs are at `/docs`. In another terminal, run `.venv\Scripts\kozphy worker`; optional scheduled tasks run with `.venv\Scripts\kozphy scheduler`.

Run `.venv\Scripts\kozphy demo` for five synthetic offline results. Checks: `.venv\Scripts\python -m pytest -q` and `.venv\Scripts\ruff check company_os migrations tests`.

Authenticated writers can store a prospect with `POST /v1/prospects`, supplying
`domain`, named boolean `criteria`, and an optional `qualification_threshold`
(default `0.7`). `GET /v1/prospects` lists the caller's tenant pipeline. Qualified
records include a local proposal draft; qualification inputs remain unverified.
Repeating the same inputs returns the stored record; changing qualification inputs
for an existing domain returns `409`. Standalone sales jobs produce evidence and
do not automatically update prospect records.

## Docker Compose

After setup, `.env` contains a generated PostgreSQL password. Run `docker compose up --build`. The API binds to loopback only; the database has no host port. PostgreSQL data uses a named volume. See [recovery notes](docs/RECOVERY.md). This is a local deployment recipe, not production readiness evidence.

## Boundaries

- GitHub webhook accepts signed `workflow_run` metadata and deduplicates delivery IDs. It does not fetch logs or write to GitHub.
- Engineering analysis accepts an authorized caller-supplied `ci-audit.export.v1`; its origin is not independently verified.
- Non-demo engineering exports and deliveries require a tenant-scoped operator record of customer authorization, bound to repository, review window, expiry, and the authorization document digest. The operator records that they reviewed customer-signed authority; this app does not verify the customer's signature or independently authenticate the customer.
- Research does not browse, sales does not contact leads, delivery does not send reports, and finance has no bank/accounting feed.
- High-risk effects can be approved and written to an outbox, but dispatch is disabled.
- Budgets enforce recorded estimates. Provider spend is zero offline; infrastructure cost is unknown.
- Production configuration fails closed until stronger identity, TLS, managed secrets and security review exist.

See [capabilities](docs/CAPABILITY_MATRIX.md), [gaps](docs/GAP_ANALYSIS.md), [threat model](docs/THREAT_MODEL.md), and [implementation plan](docs/IMPLEMENTATION_PLAN.md).

CodeRabbit review configuration and a pull request template are included. See
[Code Review Assistant setup](docs/CODE_REVIEW.md) for verified integration,
current plan limitations, and GitHub App setup if repository access changes.
