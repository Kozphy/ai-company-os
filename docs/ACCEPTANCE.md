# Acceptance status (local implementation snapshot)

Updated 2026-10-12. Status reflects only the checks listed below; it is not a production readiness claim.

| Criterion | Status | Evidence / limitation |
|---|---|---|
| A. Five offline agent workflows | IMPLEMENTED / TESTED | `tests/test_jobs_agents.py::test_all_five_agents_complete_offline`; deterministic local fixtures only |
| B. Duplicate event ingestion | PARTIAL / TESTED | Signed GitHub delivery ID maps to one idempotent job in `test_webhook_signature_and_delivery_idempotency`; external action dispatch is disabled |
| C. Recover unfinished work after restart | PARTIAL / TESTED | Expired lease is reclaimed and stale lease fenced in `test_expired_worker_fenced_and_job_recovered`; no process-kill/restart fault injection |
| D. Approval gates for high-risk operations | PARTIAL / TESTED | Actor, expiry, digest, and replay negatives covered; effect outbox has no dispatcher and production identity is unavailable |
| E. Tenant isolation | PARTIAL / TESTED | Cross-tenant job lookup and reader denial tested; no exhaustive resource/API fuzzing |
| F. Stop application-recorded spend at budget | PARTIAL / TESTED | Cost ledger idempotency and cap plus reservation rejection tested; no paid provider is configured, so provider spend enforcement is unverified |
| G. Completed deliverable has evidence | IMPLEMENTED / TESTED | Completion/evidence hash and evaluation linked in worker integration test |
| H. All tests pass in a clean environment | UNVERIFIED | Current local Python 3.12 venv: full suite result recorded below; isolated clean install and full upstream suites not complete |
| I. Cloud smoke tests | NOT RUN | Cloud deployment was not authorized or attempted |
| J. Limitations documented | IMPLEMENTED | This file, `GAP_ANALYSIS.md`, `THREAT_MODEL.md`, and pilot docs |

Additional verification: See [local implementation evidence](evidence/local-implementation-tests.md) for the latest exact command results. Customer audit exports now require a tenant-scoped operator-recorded authorization matching repository and review window; submission and worker execution check expiry, and revocation is enforced. The operator stores the authorization document digest but the app does not verify the customer's signature or identity. One Starlette/httpx deprecation warning remains. Cloud deployment remains untested. See [upstream audit evidence](evidence/phase0-tests.md).

EvalForge JSON exports from audited revision `4fcec3bc4fa816a533d3445ebc3dc82d38871659` can be imported by an operator for a tenant-owned job. Only a digest and small summary are stored; the source revision is caller-asserted. Imported failure/review counts are unverified and labeled `REVIEW_ONLY`; they never set or override the OS deterministic evaluation.

Research workflows now canonicalize HTTPS citation URLs, deduplicate sources, parse ISO publication timestamps, and preserve `UNKNOWN`, `INVALID`, or `PARSED_UNVERIFIED` date states. They do not retrieve sources or validate publisher identity, date truth, or claim reliability.

Sales qualification now shares strict boolean criteria and threshold rules between the prospect API and offline worker. The authenticated prospect API stores tenant-scoped records and proposal drafts, returns identical replays, and rejects changed qualification inputs for an existing domain. Empty criteria stay unqualified, and qualification compares the full score against the threshold. Drafts are withheld for unqualified prospects. Qualification inputs remain `CALLER_SUPPLIED_UNVERIFIED`; no prospect discovery, contact authorization verification or outreach occurs. Sales jobs store their own evidence and do not automatically update pipeline records. Regression evidence is in `tests/test_sales.py`.

Known missing acceptance scenarios include database interruption, process kill/restart, retry exhaustion, provider rate limit/timeout, invalid external tool output, full prompt injection cases, cross-tenant enumeration, partial delivery, and PostgreSQL restore. The local MVP does not satisfy the complete Phase 8 acceptance set.
