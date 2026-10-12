# Reviewable implementation plan

Phase 0 preceded application code. This snapshot contains the first local offline
vertical slice and operator-preparation packet; later phases remain incomplete.
Each boundary is a separate local commit and review packet.
Do not merge automatically. Draft remote PRs depend on a reviewed private repository
publication, network access and credentials. No cloud resources or customer
communication authorized by this plan.

## Current local progress

PR-01 is committed. PR-02 implements a broad but offline local slice: API, SQL
schema, job leases/retries/scheduling, webhook dedupe, five workflow demos,
deterministic evaluation, evidence, budgets, approval/outbox, ledger, and dashboard.
PR-03 adds local Compose/CI preparation and commercial templates. Both are local
work only; no remote repository or pull request is available. Exact status and
verified gaps are in `ACCEPTANCE.md`. The initial PR-02 slice is intentionally
more cohesive than the original PR sequence because the API, worker, schema and
workflow tests share their interfaces; subsequent live-provider and security
hardening work remains split into separate packets.

| Packet | Objective | Acceptance / migration / rollback |
|---|---|---|
| PR-01 | Audit, source manifest, ADRs, threat model | Five docs + actual test evidence; no DB migration; revert docs |
| PR-02 | FastAPI config, SQL models, Alembic | Empty clean migration, deny anonymous, schema readiness; backup/revert initial schema |
| PR-03 | Durable queue, budgets, worker lifecycle | Dedupe, stale fence, recovery, bounded retries, kill switch, outbox; additive tables; drain/backup before rollback |
| PR-04 | Engineering offline CI export | Stored input -> job -> report evidence; optional CFO adapter; no GitHub writes |
| PR-05 | Evaluation import / deterministic gate | Failing deterministic checks dominate judge; unknown blocks; versioned golden set |
| PR-06 | Research brief / schedule | Dated authorized supplied public sources, dedupe, explicit reliability unknowns; no autonomous fetch |
| PR-07 | Sales qualification / draft | Explicit qualification criteria, authorized prospect, stored pipeline; no outbound adapter |
| PR-08 | Delivery | Operator customer authorization, immutable report review and local package; no communication |
| PR-09 | Finance | Idempotent ledger, truthful summaries, costs / quota, DEMO separate |
| PR-10 | Policy / approvals | Scope+actor+expiry+digest checks, isolation, redaction, signed webhook, security negative tests |
| PR-11 | Dashboard / observability | Every value from SQL, unknowns visible, evidence drilldown; no seeded production metrics |
| PR-12 | Compose / recovery / pilot docs | Clean test env, fault tests, PostgreSQL and Compose smoke evidence; prepared cloud shape only |

Each `docs/pr/PR-NN.md` must state objective, changed files, architecture, migration,
security, tests and exact execution evidence, limitations, acceptance and rollback.
Status goes in `docs/ACCEPTANCE.md`; incomplete phases must remain explicit.

Application scope: demonstrate five workflows deterministically with no model cost.
Live model evidence, automated public retrieval, hostile-code sandbox, sending
proposals/deliverables and production authentication are separate authorization and
validation work. A runnable offline MVP does not prove 24/7 availability.
