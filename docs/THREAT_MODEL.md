# Threat model v1

Assets: customer repository metadata, evidence, tenant records, operator identity,
approval authority, provider secrets, budget, ledger integrity and private IP.
Trust boundaries: API/client, GitHub/webhook, SQL state, worker/adapters, imported
artifacts, operator/browser, upstream repositories, eventual cloud identity.

| Threat | Control / required evidence | Remaining limitation |
|---|---|---|
| Forged webhook / replay | HMAC over raw body; repo to tenant mapping from trusted config; delivery dedupe in transaction | Rotation and GitHub registration operator tasks |
| Oversized/chunked request | ASGI middleware counts declared and actual body bytes before route processing; 1 MB cap | Reverse-proxy limits still needed for hosted use |
| Cross-tenant job/evidence access | Identity from server-side token map, tenant predicates on every query; negative API tests | Local tokens are not production identity |
| Unauthorized or stale customer audit scope | Persist operator-reviewed authorization per tenant, repository, date window, digest, expiry; validate at submission and again in worker; revocation blocks later work | Operator attestation only; customer signature and identity are not independently verified |
| Approval substitution / replay | Bound actor, tenant, action, resource, expiry, canonical digest; immutable request; operator role; consumed transactionally | Trusted operator must verify customer authority |
| Prompt injection in logs / sources | Treat inputs as data, typed validation, no executable tools or outbound model enabled | Pattern detection alone is not a security boundary |
| Untrusted test execution / secret theft | Disable patch/test execution; separate offline test container without network, socket, credentials | Docker is not a hostile-code multi-tenant sandbox |
| Duplicate effects after crash | Tenant idempotency + outbox uniqueness + effect key; fenced leases | Network exactly-once is not promised; sender must support idempotency |
| Stale worker commits | Per-claim unpredictable lease token, expiry and status checks in all mutations | Clock accuracy and database availability assumptions |
| Budget race / delayed billing | Transactional reservations and fixed caps; fail closed; no paid provider by default | Provider invoices/overages outside app need external limits |
| Secret in artifact / error / UI | Recursive common-token and credential-string redaction before task persistence; generic API errors | Key-name based and provider-specific redaction is incomplete; no secret scanning can prove absence |
| Ledger duplication / fabricated revenue | Unique tenant event key, source reference, operator-only recording, DEMO separation | Manual attestations are not bank reconciliation |
| Database / backup exposure | Loopback API, unexposed DB, file permissions, managed TLS/secrets planned | Local SQLite unencrypted; do not ingest real customer secrets |
| Private code disclosure | Ignore `.audit`, minimal adapter contracts; private new repository default | Publication requires a reviewed allowlist |
| Emergency stop race | Persistent global and tenant kill switches checked on admission and worker claim | Cannot recall effects already accepted remotely; outbox dispatch is disabled |
| Unsafe cloud rollout | Preparation only, managed external state, no provisioning | Cloud smoke tests require approval |

Default denied: code execution, PR creation, email sending, merges, financial
transfers, refunds, trading, cloud provisioning. Adding an action requires an
allowlisted adapter plus immutable approval checks at the effect boundary. Source
content, model output and client roles cannot modify policy or grant authority.

Security tests are necessary but do not establish production security or formal
audit certification. No legal/regulatory assurance is offered.
