# Phase 0 capability matrix

Snapshot: 2026-10-12. IMPLEMENTED means inspected code exists; it does not mean
executed, operational, secure, or production validated. PARTIAL means only part of
the requested contract exists. SIMULATED means fixture evidence only. UNVERIFIED
means evidence was not obtained. MISSING means no implementation was identified in
the inspected relevant paths, not a proof about every file in the source tree.

Sources are independent checkouts under ignored `.audit/`; never redistribute
them as part of this repository. Paths below are relative to the named checkout.

| Asset | Inspected revision | Access / license |
|---|---|---|
| ci-failure-orchestrator (CFO) | f7b6cf2e65b3d2ef3f15cecb4fc1c65874c3f56f | Public; MIT |
| EvalForge (EF) | 4fcec3bc4fa816a533d3445ebc3dc82d38871659 | Public portfolio mirror; proprietary, not open source |
| Windows-Network-Recovery-Toolkit (WNRT) | 83ce00e1d3b5857131f0decc943943d18789b30f | GitHub connector confirms PRIVATE; AGPL-3.0-only; documented private/public split |
| ai-company-os | empty local Git workspace; remote lookup 404 | New local implementation; no inherited product evidence |

GitHub metadata was read through the authenticated connector. A 404 for the new
repository means unavailable to that connection at audit time. The WNRT public
mirror is a different repository and was not substituted for private source.

## Inspected reusable contracts

| Capability | Status at Phase 0 | Code evidence | Existing test reference (not execution claim) |
|---|---|---|---|
| CI read-only history collection | IMPLEMENTED | CFO `ci_failure_orchestrator/ci_audit/collect.py`, `GitHubActionsClient` in `github_client.py` | `tests/test_ci_audit.py` uses FakeReader |
| CI metrics / Markdown report | IMPLEMENTED | CFO `ci_audit/analyze.py::analyze_export`, `report.py::render_report`; schema `ci-audit.export.v1` | `tests/test_ci_audit.py` |
| Failure classification / evidence lines | IMPLEMENTED | CFO `doctor/diagnose.py`, `foundation/classifier.py` | `tests/test_doctor.py` |
| Candidate patch verification | PARTIAL | CFO `patch_sandbox.py::WorktreePatchVerifier` uses subprocesses in worktrees, not an OS sandbox | `tests/test_patch_sandbox.py` |
| Regression / test weakening gates | IMPLEMENTED | CFO `service/verification.py`, `foundation/policy.py` | `tests/test_verification_integrity.py`, foundation suites |
| Draft PR proposal | PARTIAL | CFO `service/apply.py`; requires isolation and action scoped authorization in the OS | apply tests; live writes not exercised |
| FastAPI / durable SQL queue | PARTIAL | CFO `server/app.py`, `server/db.py`, `server/jobs.py` | `tests/test_server_api.py`, `test_server_worker.py`, `test_durable_store_contract.py` |
| Lease recovery / fencing | PARTIAL | CFO `server/jobs.py`: stale jobs move to REQUIRES_REVIEW, not requested retry lifecycle | server worker / queue suites |
| Idempotent submission | IMPLEMENTED | CFO `server/jobs.py::enqueue`, request digest | server API / worker suites |
| Default strong authentication / tenant isolation | MISSING | CFO `server/settings.py` allows `api_token=None`; shared token explicitly not RBAC | OS must implement its own contract |
| Finance golden dataset | IMPLEMENTED | EF `finance_eval/dataset/finance_accounting_v1.jsonl`, `MANIFEST.json` | `tests/test_finance_eval.py` |
| Deterministic graders / regression | IMPLEMENTED | EF `finance_eval/graders.py`, `policy.py`, `app/graders.py`, `app/regression.py` | `tests/test_graders.py`, `test_regression.py`, `test_finance_eval.py` |
| Versioned evaluation / evidence | IMPLEMENTED | EF `app/control_plane/contracts/__init__.py`, `evidence/store.py` | `tests/test_control_plane_contracts.py`, `test_control_plane.py` |
| LLM judging / human reviews | SIMULATED | EF `finance_eval/judge.py`, `human_review.py`; README distinguishes planted data | finance tests are not live-model evidence |
| Live model capability | UNVERIFIED | EF `finance_eval/live.py`; no credentials used or paid calls authorized | `tests/test_finance_live.py` includes mock paths |
| Local EF operator API | PARTIAL | EF `app/main.py`: routes lack authentication dependencies | `tests/test_operator_ui.py`, `test_api.py` |
| Endpoint governance / proof tiers | IMPLEMENTED | WNRT `src/platform_core/principles/validator.py`, governance, evidence modules | `tests/test_observation_not_proof.py` and principle suites |
| Endpoint remediation | UNVERIFIED | WNRT `windows_network_toolkit/`, policy / typed token controls | Windows execution deliberately not attempted |
| WNRT API auth | PARTIAL | `backend/auth/dependencies.py`: demo token default; separate JWT routes exist | `tests/test_api_hardening_contract.py` |
| WNRT predictive API exposure | PARTIAL | `api/app.py`: wildcard CORS, no route authentication in inspected surface | not suitable as an internet service |

## Requested OS capabilities not yet integrated at audit time

| Requirement group | Status | Phase / reason |
|---|---|---|
| Modular Python API, worker, scheduler, migrations | MISSING | New application, PR-02/03 |
| All nine job states and required job fields | MISSING | CFO lifecycle differs; PR-03 |
| Jitter, bounded retries, DLQ, cancellation, concurrency, kill switch | MISSING | Unified OS contract absent |
| Durable event dedupe and transactional outbox | MISSING | Unified tenant scoped effect contract absent |
| Budget reservations / provider quotas | MISSING | EF estimates are not cross-agent enforcement |
| Scoped immutable approvals / audit storage | MISSING | OS needs action + resource + actor + expiry + digest |
| Engineering agent integration | PARTIAL | CFO available; safe host execution cannot be assumed |
| Research retrieval / dated citations / archive / schedule | MISSING | No integrated OS workflow |
| Sales qualification / proposal / pipeline | MISSING | No integrated OS workflow |
| Customer authorization / read-only audit delivery / sign-off | PARTIAL | CFO reports reusable; business controls absent |
| Finance verified ledger / margin / summaries | MISSING | Evaluation of finance responses is not bookkeeping |
| Deterministic-first evaluation integration / unknown states | PARTIAL | EF interface exists; no OS adapter |
| Tenant RBAC / resource auth / prompt boundaries | MISSING | Must fail closed in new application |
| Encrypted secret store / production identity / rotation | MISSING | Local config is not managed secret storage |
| Sandbox for untrusted patches | MISSING | Worktree is insufficient |
| Dashboard of stored business metrics / OTel interface | MISSING | Existing dashboards are not OS records |
| Compose / PostgreSQL / health / recovery | PARTIAL | Upstream configs exist; new app needs validation |
| Azure scale-to-zero / backups / rollback / budget warnings | MISSING | Prepare only; provisioning needs approval |
| Five offline demos / fault / security acceptance suite | MISSING | No combined baseline |
| Pilot templates / onboarding / unit economics | PARTIAL | CFO pricing copy exists; USD149 remains a hypothesis |
| Paid customers / revenue / 24x7 availability / production readiness | UNVERIFIED | No evidence obtained; never infer from README |

This is the preimplementation baseline. Subsequent work is tracked separately in
`docs/ACCEPTANCE.md`; do not retroactively upgrade upstream evidence.

## Local OS implementation updates

These statuses describe code added after the source snapshot above; IMPLEMENTED
means the described local path exists, not that it is production validated.

| Capability | Current status | Local source / test evidence |
|---|---|---|
| Customer authorization bound to tenant, repository, date window, digest, expiry and revocation | PARTIAL | `company_os/authorization.py`, `company_os/api.py`, migration `0002`; `tests/test_jobs_agents.py` authorization/revocation/expiry cases |
| Delivery linked to same-tenant evidence and valid authorization | IMPLEMENTED / TESTED | `company_os/worker.py`; `tests/test_jobs_agents.py::test_delivery_requires_stored_same_tenant_evidence` |
| EvalForge JSON artifact import | PARTIAL / TESTED | `company_os/evalforge_import.py`, `company_os/api.py`; `tests/test_evalforge_import.py`; imported verdict stays `UNVERIFIED_IMPORTED` / `REVIEW_ONLY` |
| EvalForge source/model execution or independently reproduced metrics | MISSING | No server/source dependency or live model call; proprietary source remains separate |
| Customer identity and signed authorization verification | MISSING | Operator attestation and document digest only |
