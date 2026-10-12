# Source-backed gap analysis

## Highest value gap and first experiment

The assets do not form a tenant-safe, durable business workflow. Hypothesis: one
authorized saved CI history export can become a queued job, deterministic audit,
hashed evidence, and reviewable report after a worker restart, without a GitHub
write, model bill, or host execution of customer code. Test this before adding
live providers. Acceptance: submit twice -> one job; crash -> leased retry; stale
worker cannot finalize; report totals match saved input; unauthorized tenant gets
404; completed job has evidence; cost reservation cannot exceed configured cap.

## Findings from inspected code

1. CFO `server/settings.py` defaults to no API token and explicitly documents that
   its optional shared token is not RBAC. Reuse pure domain functions, not that
   server as the OS security boundary.
2. CFO `patch_sandbox.py` runs allowlisted subprocesses in a git worktree. It
   prevents checkout mutation but does not isolate the host, network, filesystem,
   or environment from test code. Patch execution stays disabled in this MVP.
3. CFO `ci_audit/analyze.py` uses static OS billing multipliers and recommends
   quarantine/deletion of flaky tests in one finding. OS reporting must label
   minute estimates, avoid presenting them as invoices, and replace suggestions
   that could weaken mandatory gates. No repair execution or merging is enabled.
4. CFO `.github/workflows/auto-merge-after-checks.yml` contains merge code but is
   disabled with `if: false` and manual-only trigger. Do not import that workflow.
5. EF `app/main.py` exposes local workbench/operator routes without authentication
   dependencies; `app/control_plane/policy/engine.py` starts ALLOW if no rule
   matches. Wrap exported results with OS default-deny policy; do not expose EF.
6. EF `finance_eval/policy.py` evaluates numeric release thresholds; it is not
   financial ledger integrity, financial advice, or deployment authorization.
   Offline judging and seeded review evidence remain SIMULATED.
7. WNRT `backend/auth/dependencies.py` has a demo token fallback. Its separate
   `api/app.py` uses wildcard CORS with no inspected authentication. Its private
   source includes billing/fleet surfaces excluded by the public mirror rules.
   Keep all code and sensitive findings local; no vendoring or public export.
8. No live secrets were verified. Secret-pattern hits include synthetic GitHub
   tokens in tests and demo defaults. A static scan cannot certify absence of
   secrets, revocation, history hygiene, or account configuration.

## Duplication and integration decisions

All three projects contain policy, evidence, review and reporting concepts. CFO
and EF both implement local persistence / async execution; WNRT includes extra
worker, SaaS and telemetry stacks. Importing entire servers would create multiple
sources of truth, divergent auth and job lifecycles, and unnecessary dependencies.

Use one SQL database and one business job engine. CFO supplies CI export analysis
through a pinned optional adapter. EF supplies separately generated versioned
evaluation artifacts through a validated import contract. WNRT supplies optional
redacted evidence artifacts; Windows operations remain outside this application.
Do not copy proprietary or AGPL source into the new repo. Owner instructions
authorize integration, not indiscriminate redistribution or relicensing.

## Test / license limitations

Upstream tests run only in disposable, non-root containers, with network disabled,
no credentials or Docker socket, source mounted read-only and copied to temporary
storage. Only selected deterministic suites are appropriate; full suites can
execute subprocesses, host diagnostics, or optional providers. Exact commands and
outcomes belong in `docs/evidence/phase0-tests.md` after execution. CI YAML is a
test reference, not evidence that a workflow ran successfully.

Source licenses: CFO MIT, EF proprietary, WNRT AGPL-3.0-only. Source manifests use
broad lower dependency bounds rather than fully resolved locks. Dependency license
inventory for the new resolved environment is required before publication; this
audit is not legal clearance. Neither Windows production behavior, live models,
actual pilot income, nor cloud reliability was exercised.
