"""Local HTTP API for jobs, operator controls, and the offline workflows."""

import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from company_os.authorization import AuthorizationError, validate_export
from company_os.body_limit import BodyLimitMiddleware
from company_os.config import Settings
from company_os.db import make_engine, ready, transaction
from company_os.evalforge_import import EvalForgeImportError, summarize_export
from company_os.jobs import JOB_TYPES, Conflict, cancel, submit
from company_os.sales import ProspectInput as ProspectRequest
from company_os.sales import qualify
from company_os.schema import (
    approvals,
    audit,
    authorizations,
    budgets,
    control,
    evaluations,
    evidence,
    flags,
    jobs,
    ledger,
    outbox,
    prospects,
    schedules,
)
from company_os.security import Identity, authenticate, digest, require_operator, require_writer
from company_os.worker import Worker

Principal = Annotated[Identity, Depends(authenticate)]


class JobRequest(BaseModel):
    """Body for ``POST /v1/jobs``.

    Attributes:
        job_type: Offline workflow to run.
        idempotency_key: Tenant-scoped replay key.
        payload: Workflow input. Extra fields on this model itself are rejected.
        maximum_attempts: Attempts before the job is dead-lettered.
    """

    model_config = ConfigDict(extra="forbid")
    job_type: Literal["engineering", "research", "sales", "delivery", "finance"]
    idempotency_key: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any]
    maximum_attempts: int = Field(default=3, ge=1, le=8)


class ApprovalRequest(BaseModel):
    """Body for ``POST /v1/approvals``.

    Attributes:
        actor_id: Operator the approval is bound to. It must match the caller.
        action: Approved effect, ``delivery.package`` or ``sales.proposal``.
        resource: Resource the effect may name.
        payload: Exact payload whose digest the effect must repeat.
        lifetime_seconds: Seconds until the unused approval expires.
    """

    model_config = ConfigDict(extra="forbid")
    actor_id: str = Field(min_length=1, max_length=128)
    action: Literal["delivery.package", "sales.proposal"]
    resource: str = Field(min_length=1, max_length=256)
    payload: dict[str, Any]
    lifetime_seconds: int = Field(default=900, ge=30, le=86400)


class EffectRequest(BaseModel):
    """Body for ``POST /v1/effects``.

    Attributes:
        approval_id: Unused approval that must match this payload.
        effect_key: Tenant-scoped idempotency key for the outbox row.
        payload: Effect body. Its digest must equal the approval digest.
    """

    model_config = ConfigDict(extra="forbid")
    approval_id: str
    effect_key: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any]


class LedgerRequest(BaseModel):
    """Body for ``POST /v1/ledger``.

    Attributes:
        event_key: Tenant-scoped idempotency key.
        kind: ``income``, ``expense``, ``llm_cost``, or ``cloud_cost``.
        amount_micro_usd: Nonnegative amount in millionths of a USD.
        source_reference: Caller-supplied source label. It is not verified.
        verified: Must stay false. Independent verification is unavailable.
        demo: Marks the entry as demonstration data.
        details: Short string annotations stored with the entry.
    """

    model_config = ConfigDict(extra="forbid")
    event_key: str = Field(min_length=1, max_length=128)
    kind: Literal["income", "expense", "llm_cost", "cloud_cost"]
    amount_micro_usd: int = Field(ge=0, le=10**15)
    source_reference: str = Field(min_length=1, max_length=256)
    verified: bool = False
    demo: bool = False
    details: dict[str, str] = Field(default_factory=dict)


class BudgetRequest(BaseModel):
    """Body for ``PUT /v1/budget``.

    Attributes:
        limit_micro_usd: Tenant ceiling in millionths of a USD.
    """

    model_config = ConfigDict(extra="forbid")
    limit_micro_usd: int = Field(ge=0, le=10**15)


class ScheduleRequest(BaseModel):
    """Body for ``POST /v1/schedules``.

    Attributes:
        job_type: Workflow submitted on each tick.
        payload: Job payload repeated on each tick.
        interval_seconds: Delay between ticks, from one hour to one year.
    """

    model_config = ConfigDict(extra="forbid")
    job_type: Literal["engineering", "research", "sales", "delivery", "finance"]
    payload: dict[str, Any]
    interval_seconds: int = Field(ge=3600, le=31_536_000)


class AuthorizationRequest(BaseModel):
    """Body for ``POST /v1/authorizations``.

    Attributes:
        customer_name: Customer named by the operator.
        signer_name: Person the operator records as the signer.
        repository: Authorized ``owner/name`` repository.
        window_start: Inclusive first day of the audit window.
        window_end: Inclusive last day of the audit window.
        authorization_digest: Caller-supplied SHA-256 hex digest of the
            authorization document.
        lifetime_seconds: How long the stored record stays active.
    """

    model_config = ConfigDict(extra="forbid")
    customer_name: str = Field(min_length=1, max_length=256)
    signer_name: str = Field(min_length=1, max_length=256)
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}$")
    window_start: date
    window_end: date
    authorization_digest: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    lifetime_seconds: int = Field(default=2_592_000, ge=60, le=7_776_000)

    @model_validator(mode="after")
    def validate_window(self) -> "AuthorizationRequest":
        """Reject an inverted, oversized, or future-dated window.

        Returns:
            This request.

        Raises:
            ValueError: The window is longer than 90 days, ends before it
                starts, or ends after today.
        """
        if self.window_end < self.window_start:
            raise ValueError("authorization window end precedes start")
        if (self.window_end - self.window_start).days > 90:
            raise ValueError("authorization window cannot exceed 90 days")
        if self.window_end > date.today():
            raise ValueError("authorization window must not extend into the future")
        return self


class EvalForgeImportRequest(BaseModel):
    """Body for ``POST /v1/jobs/{job_id}/evaluations/evalforge``.

    Attributes:
        source_revision: Forty-character revision the caller claims produced
            the artifact.
        artifact_json: Raw EvalForge export JSON. Raw rows are not stored.
    """

    model_config = ConfigDict(extra="forbid")
    source_revision: str = Field(min_length=40, max_length=40)
    artifact_json: str = Field(min_length=2, max_length=900_000)


class KillSwitchRequest(BaseModel):
    """Body for the tenant and global kill-switch endpoints.

    Attributes:
        enabled: ``True`` stops new work. ``False`` allows it again.
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the local API, including the request-size limit.

    Args:
        settings: Runtime settings. When omitted, settings load from the
            environment.

    Returns:
        An application whose engine and settings live on ``app.state``.
    """
    settings = settings or Settings()
    app = FastAPI(title="Kozphy AI Company OS — local MVP", version="0.1.0")
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)

    app.add_middleware(BodyLimitMiddleware, max_bytes=1_000_000)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report that the process is up.

        Returns:
            A local-MVP status. This does not check the database.
        """
        return {"status": "ok", "maturity": "local MVP"}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def operator_dashboard() -> str:
        """Return the operator dashboard HTML.

        Returns:
            The packaged ``dashboard.html`` document. It does not embed credentials.
        """
        return (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")

    @app.get("/ready")
    def readiness() -> JSONResponse:
        """Report whether the migrated control database is reachable.

        Returns:
            HTTP 200 when revision ``0002`` and the control row are present,
            otherwise HTTP 503.
        """
        available = ready(app.state.engine)
        return JSONResponse({"ready": available}, status_code=200 if available else 503)

    @app.get("/v1/me")
    def me(identity: Principal) -> dict[str, str]:
        """Return the authenticated tenant, actor, and role.

        Args:
            identity: Caller resolved from the bearer token.

        Returns:
            The caller's identity fields.
        """
        return {"tenant_id": identity.tenant_id, "actor_id": identity.actor_id, "role": identity.role}

    @app.post("/v1/jobs", status_code=202)
    def create_job(body: JobRequest, identity: Principal) -> dict:
        """Queue a workflow job for the caller's tenant.

        Engineering jobs require a covering customer authorization unless the
        caller is an operator and the payload sets ``demo`` to true. Writers only.

        Args:
            body: Job type, idempotency key, and payload.
            identity: Authenticated writer.

        Returns:
            The job id, current status, and whether this call created it.

        Raises:
            HTTPException: The caller cannot write, the engineering
                authorization does not cover the export, or the queue rejects
                the request as a conflict or invalid payload.
        """
        require_writer(identity)
        if body.job_type == "engineering":
            if body.payload.get("demo") is True and identity.role == "operator":
                pass
            else:
                try:
                    validate_export(app.state.engine, identity.tenant_id, body.payload)
                except AuthorizationError as exc:
                    raise HTTPException(
                        403, "customer authorization is expired or outside its scope"
                    ) from exc
        try:
            result = submit(
                app.state.engine,
                tenant=identity.tenant_id,
                actor=identity.actor_id,
                kind=body.job_type,
                key=body.idempotency_key,
                payload=body.payload,
                maximum_attempts=body.maximum_attempts,
                budget_limit=settings.tenant_budget_micro_usd,
            )
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"job_id": result.job_id, "status": result.status, "created": result.created}

    @app.post("/v1/webhooks/github", status_code=202)
    async def github_webhook(request: Request) -> dict:
        """Queue an engineering job from a signed GitHub ``workflow_run`` event.

        Ingestion is disabled when no webhook secret is configured. Only
        completed failure and timeout conclusions for a routed repository are
        queued. The stored payload is event metadata, not logs.

        Args:
            request: Raw GitHub delivery. ``X-Hub-Signature-256`` must match
                the configured secret.

        Returns:
            Whether the event was accepted and, when queued, the job id.

        Raises:
            HTTPException: The webhook is disabled, the signature or event
                shape is invalid, the repository is not routed, or the
                delivery id conflicts with a different payload.
        """
        if not settings.webhook_secret:
            raise HTTPException(404, "webhook ingestion is disabled")
        raw = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(settings.webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(401, "invalid webhook signature")
        if request.headers.get("X-GitHub-Event") != "workflow_run":
            raise HTTPException(422, "unsupported event")
        try:
            data = json.loads(raw)
            repo = data["repository"]["full_name"]
            run = data["workflow_run"]
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, "invalid workflow event") from exc
        routes = json.loads(settings.webhook_routes_json)
        route = routes.get(repo)
        if not isinstance(route, dict) or set(route) != {"tenant_id", "actor_id"}:
            raise HTTPException(403, "repository is not authorized")
        if data.get("action") != "completed" or run.get("conclusion") not in {"failure", "timed_out"}:
            return {"accepted": True, "queued": False, "reason": "event outside audit trigger"}
        delivery_id = request.headers.get("X-GitHub-Delivery", "")
        if not re.fullmatch(r"[A-Za-z0-9-]{16,128}", delivery_id):
            raise HTTPException(422, "valid delivery id required")
        payload = {
            "event": "workflow_run",
            "repository": repo,
            "run_id": run.get("id"),
            "name": str(run.get("name", ""))[:256],
            "head_sha": str(run.get("head_sha", ""))[:64],
            "conclusion": run.get("conclusion"),
            "html_url": str(run.get("html_url", ""))[:2000],
            "details": (
                "GitHub event metadata only; log retrieval requires a separately authorized read adapter."
            ),
        }
        try:
            result = submit(
                app.state.engine,
                tenant=route["tenant_id"],
                actor=route["actor_id"],
                kind="engineering",
                key="github-" + delivery_id,
                payload=payload,
                budget_limit=settings.tenant_budget_micro_usd,
                event_key="github-" + delivery_id,
            )
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"accepted": True, "queued": result.created, "job_id": result.job_id}

    @app.get("/v1/jobs")
    def list_jobs(identity: Principal, limit: int = 100) -> list[dict]:
        """List the caller's jobs, newest first.

        Args:
            identity: Authenticated caller. Results stay inside this tenant.
            limit: Page size from 1 to 200. Values outside that range are clamped.

        Returns:
            Job views without payloads.
        """
        limit = min(max(limit, 1), 200)
        with app.state.engine.connect() as conn:
            rows = conn.execute(
                sa.select(jobs)
                .where(jobs.c.tenant_id == identity.tenant_id)
                .order_by(jobs.c.created_at.desc())
                .limit(limit)
            ).all()
        return [_job_view(row) for row in rows]

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, identity: Principal) -> dict:
        """Return one job in the caller's tenant.

        Args:
            job_id: Job identifier.
            identity: Authenticated caller.

        Returns:
            The job view.

        Raises:
            HTTPException: No job with this id exists in the tenant.
        """
        with app.state.engine.connect() as conn:
            row = conn.execute(
                sa.select(jobs).where(jobs.c.tenant_id == identity.tenant_id, jobs.c.job_id == job_id)
            ).first()
        if row is None:
            raise HTTPException(404, "job not found")
        return _job_view(row)

    @app.post("/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, identity: Principal) -> dict:
        """Cancel a queued, waiting, or approval-pending job.

        Args:
            job_id: Job identifier.
            identity: Authenticated writer.

        Returns:
            Whether the job was cancelled. An active or missing job returns
            ``cancelled`` false.

        Raises:
            HTTPException: The caller cannot write.
        """
        require_writer(identity)
        return {"cancelled": cancel(app.state.engine, identity.tenant_id, job_id)}

    @app.get("/v1/jobs/{job_id}/evidence")
    def get_evidence(job_id: str, identity: Principal) -> dict:
        """Return the stored report for one job.

        Args:
            job_id: Job identifier.
            identity: Authenticated caller.

        Returns:
            The evidence id, job id, digest, and report body.

        Raises:
            HTTPException: This tenant has no evidence for the job.
        """
        with app.state.engine.connect() as conn:
            row = conn.execute(
                sa.select(evidence).where(
                    evidence.c.tenant_id == identity.tenant_id, evidence.c.job_id == job_id
                )
            ).first()
        if row is None:
            raise HTTPException(404, "evidence not found")
        return {"evidence_id": row.id, "job_id": row.job_id, "sha256": row.digest, "evidence": row.body}

    @app.post("/v1/jobs/{job_id}/evaluations/evalforge", status_code=201)
    def import_evalforge_evaluation(
        job_id: str, body: EvalForgeImportRequest, identity: Principal
    ) -> dict:
        """Attach a review-only EvalForge summary to an existing job.

        The same artifact digest is stored once. The import does not change
        the job status or the deterministic gate. Operators only.

        Args:
            job_id: Job that receives the supplementary evaluation.
            body: Pinned source revision and raw export JSON.
            identity: Authenticated operator.

        Returns:
            The evaluation id and the review-only summary.

        Raises:
            HTTPException: The caller is not an operator, the job is outside
                the tenant, or the artifact is rejected.
        """
        require_operator(identity)
        with app.state.engine.connect() as conn:
            job = conn.execute(
                sa.select(jobs.c.job_id).where(
                    jobs.c.tenant_id == identity.tenant_id, jobs.c.job_id == job_id
                )
            ).first()
        if job is None:
            raise HTTPException(404, "job not found")
        try:
            summary = summarize_export(body.artifact_json, body.source_revision)
        except EvalForgeImportError as exc:
            raise HTTPException(422, str(exc)) from exc
        identifier = digest(
            {
                "tenant_id": identity.tenant_id,
                "job_id": job_id,
                "artifact_sha256": summary["artifact_sha256"],
            }
        )
        with transaction(app.state.engine) as conn:
            existing = conn.execute(
                sa.select(evaluations).where(
                    evaluations.c.tenant_id == identity.tenant_id,
                    evaluations.c.job_id == job_id,
                    evaluations.c.version == "evalforge-import-v1",
                    evaluations.c.id == identifier,
                )
            ).first()
            if existing is None:
                conn.execute(
                    evaluations.insert().values(
                        id=identifier,
                        tenant_id=identity.tenant_id,
                        job_id=job_id,
                        version="evalforge-import-v1",
                        body=summary,
                        created_at=time.time(),
                    )
                )
        return {"evaluation_id": identifier, "evaluation": summary}

    @app.post("/v1/worker/run-once")
    def run_worker(identity: Principal) -> dict:
        """Claim and process at most one job in this process.

        Args:
            identity: Authenticated operator.

        Returns:
            Whether a job was processed.

        Raises:
            HTTPException: The caller is not an operator.
        """
        require_operator(identity)
        return {"processed": Worker(app.state.engine, lease_seconds=settings.lease_seconds).run_once()}

    @app.get("/v1/dashboard")
    def dashboard(identity: Principal) -> dict:
        tenant = identity.tenant_id
        with app.state.engine.connect() as conn:
            counts = dict(
                conn.execute(
                    sa.select(jobs.c.status, sa.func.count())
                    .where(jobs.c.tenant_id == tenant)
                    .group_by(jobs.c.status)
                ).all()
            )
            budget = conn.execute(sa.select(budgets).where(budgets.c.tenant_id == tenant)).first()
            cost_rows = conn.execute(
                sa.select(ledger.c.kind, sa.func.sum(ledger.c.amount_micro_usd))
                .where(ledger.c.tenant_id == tenant, ledger.c.kind.in_(["llm_cost", "cloud_cost"]))
                .group_by(ledger.c.kind)
            ).all()
            recorded_costs = dict(cost_rows)
            approval_count = conn.execute(
                sa.select(sa.func.count())
                .select_from(approvals)
                .where(
                    approvals.c.tenant_id == tenant,
                    approvals.c.used_at.is_(None),
                    approvals.c.expires_at > time.time(),
                )
            ).scalar_one()
            income_claims = conn.execute(
                sa.select(sa.func.coalesce(sa.func.sum(ledger.c.amount_micro_usd), 0)).where(
                    ledger.c.tenant_id == tenant,
                    ledger.c.kind == "income",
                    ledger.c.demo.is_(False),
                )
            ).scalar_one()
            prospect_rows = conn.execute(
                sa.select(prospects.c.stage, sa.func.count())
                .where(prospects.c.tenant_id == tenant)
                .group_by(prospects.c.stage)
            ).all()
            history = conn.execute(
                sa.select(evaluations.c.job_id, evaluations.c.version, evaluations.c.created_at)
                .where(evaluations.c.tenant_id == tenant)
                .order_by(evaluations.c.created_at.desc())
                .limit(20)
            ).all()
        return {
            "jobs": counts,
            "pending_approvals": approval_count,
            "agents": {
                name: {"status": "OFFLINE_DEMO_AVAILABLE"} for name in sorted(JOB_TYPES)
            },
            "costs": {
                "recorded_budget_spend_micro_usd": budget.spent_micro_usd if budget else 0,
                "llm_cost_micro_usd": recorded_costs.get("llm_cost", 0) or 0,
                "cloud_cost_micro_usd": recorded_costs.get("cloud_cost", 0) or 0,
                "reserved_micro_usd": budget.reserved_micro_usd if budget else 0,
                "infrastructure_cost_micro_usd": None,
                "infrastructure_cost_status": "UNKNOWN",
            },
            "sales_pipeline": dict(prospect_rows),
            "bank_verified_income_micro_usd": None,
            "recorded_income_claims_micro_usd": income_claims,
            "bank_verification_status": "UNAVAILABLE",
            "evaluation_history": [dict(row._mapping) for row in history],
            "demo_data": False,
            "unavailable_metrics": ["external infrastructure cost"],
        }

    @app.put("/v1/budget", status_code=200)
    def set_budget(body: BudgetRequest, identity: Principal) -> dict:
        require_operator(identity)
        with transaction(app.state.engine) as conn:
            current = conn.execute(
                sa.select(budgets).where(budgets.c.tenant_id == identity.tenant_id)
            ).first()
            if current and body.limit_micro_usd < current.reserved_micro_usd + current.spent_micro_usd:
                raise HTTPException(409, "budget cannot be lower than reserved and recorded spend")
            if current:
                conn.execute(
                    budgets.update()
                    .where(budgets.c.tenant_id == identity.tenant_id)
                    .values(limit_micro_usd=body.limit_micro_usd)
                )
            else:
                conn.execute(
                    budgets.insert().values(
                        tenant_id=identity.tenant_id,
                        limit_micro_usd=body.limit_micro_usd,
                        reserved_micro_usd=0,
                        spent_micro_usd=0,
                    )
                )
            return {"limit_micro_usd": body.limit_micro_usd}

    @app.put("/v1/kill-switch")
    def set_kill_switch(body: KillSwitchRequest, identity: Principal) -> dict:
        require_operator(identity)
        with transaction(app.state.engine) as conn:
            result = conn.execute(
                flags.update()
                .where(flags.c.tenant_id == identity.tenant_id, flags.c.key == "kill_switch")
                .values(enabled=body.enabled)
            )
            if result.rowcount == 0:
                conn.execute(
                    flags.insert().values(
                        tenant_id=identity.tenant_id, key="kill_switch", enabled=body.enabled
                    )
                )
            conn.execute(
                audit.insert().values(
                    id=str(uuid.uuid4()),
                    tenant_id=identity.tenant_id,
                    actor_id=identity.actor_id,
                    action="kill_switch.set",
                    resource=identity.tenant_id,
                    correlation_id=str(uuid.uuid4()),
                    created_at=time.time(),
                    details={"enabled": body.enabled},
                )
            )
        return {"tenant_id": identity.tenant_id, "enabled": body.enabled}

    @app.put("/v1/global-kill-switch")
    def set_global_kill_switch(body: KillSwitchRequest, identity: Principal) -> dict:
        require_operator(identity)
        with transaction(app.state.engine) as conn:
            conn.execute(control.update().where(control.c.id == 1).values(stopped=body.enabled))
            conn.execute(
                audit.insert().values(
                    id=str(uuid.uuid4()),
                    tenant_id=identity.tenant_id,
                    actor_id=identity.actor_id,
                    action="global_kill_switch.set",
                    resource="global",
                    correlation_id=str(uuid.uuid4()),
                    created_at=time.time(),
                    details={"enabled": body.enabled},
                )
            )
        return {"enabled": body.enabled}

    @app.post("/v1/schedules", status_code=201)
    def create_schedule(body: ScheduleRequest, identity: Principal) -> dict:
        require_operator(identity)
        ident, now = str(uuid.uuid4()), time.time()
        with transaction(app.state.engine) as conn:
            conn.execute(
                schedules.insert().values(
                    id=ident,
                    tenant_id=identity.tenant_id,
                    actor_id=identity.actor_id,
                    job_type=body.job_type,
                    body=body.payload,
                    interval_seconds=body.interval_seconds,
                    next_at=now + body.interval_seconds,
                    enabled=True,
                )
            )
        return {"schedule_id": ident, "enabled": True, "first_run_at": now + body.interval_seconds}

    @app.get("/v1/schedules")
    def list_schedules(identity: Principal) -> list[dict]:
        with app.state.engine.connect() as conn:
            rows = conn.execute(
                sa.select(schedules)
                .where(schedules.c.tenant_id == identity.tenant_id)
                .order_by(schedules.c.next_at)
            ).all()
        return [
            {
                "schedule_id": row.id,
                "job_type": row.job_type,
                "interval_seconds": row.interval_seconds,
                "next_at": row.next_at,
                "enabled": row.enabled,
            }
            for row in rows
        ]

    @app.post("/v1/authorizations", status_code=201)
    def record_authorization(body: AuthorizationRequest, identity: Principal) -> dict:
        require_operator(identity)
        now, authorization_id = time.time(), str(uuid.uuid4())
        scope = {
            "customer_name": body.customer_name,
            "signer_name": body.signer_name,
            "repository": body.repository,
            "window_start": body.window_start.isoformat(),
            "window_end": body.window_end.isoformat(),
            "authorization_digest": body.authorization_digest.lower(),
        }
        scope_hash = digest(scope)
        expires_at = now + body.lifetime_seconds
        with transaction(app.state.engine) as conn:
            conn.execute(
                authorizations.insert().values(
                    id=authorization_id,
                    tenant_id=identity.tenant_id,
                    repository=body.repository,
                    customer_name=body.customer_name,
                    signer_name=body.signer_name,
                    window_start=body.window_start.isoformat(),
                    window_end=body.window_end.isoformat(),
                    authorization_digest=body.authorization_digest.lower(),
                    scope_digest=scope_hash,
                    created_by=identity.actor_id,
                    authorized_at=now,
                    expires_at=expires_at,
                    status="ACTIVE",
                    revoked_at=None,
                )
            )
            conn.execute(
                audit.insert().values(
                    id=str(uuid.uuid4()),
                    tenant_id=identity.tenant_id,
                    actor_id=identity.actor_id,
                    action="customer_authorization.record",
                    resource=authorization_id,
                    correlation_id=authorization_id,
                    created_at=now,
                    details={
                        "repository": body.repository,
                        "scope_digest": scope_hash,
                        "authorization_digest": body.authorization_digest.lower(),
                        "expires_at": expires_at,
                    },
                )
            )
        return {
            "authorization_id": authorization_id,
            "repository": body.repository,
            "scope_digest": scope_hash,
            "status": "ACTIVE",
            "expires_at": expires_at,
        }

    @app.get("/v1/authorizations")
    def list_authorizations(identity: Principal) -> list[dict]:
        with app.state.engine.connect() as conn:
            rows = conn.execute(
                sa.select(authorizations)
                .where(authorizations.c.tenant_id == identity.tenant_id)
                .order_by(authorizations.c.authorized_at.desc())
            ).all()
        return [
            {
                "authorization_id": row.id,
                "repository": row.repository,
                "window_start": row.window_start,
                "window_end": row.window_end,
                "scope_digest": row.scope_digest,
                "status": row.status,
                "expires_at": row.expires_at,
            }
            for row in rows
        ]

    @app.post("/v1/authorizations/{authorization_id}/revoke")
    def revoke_authorization(authorization_id: str, identity: Principal) -> dict:
        require_operator(identity)
        now = time.time()
        with transaction(app.state.engine) as conn:
            row = conn.execute(
                sa.select(authorizations).where(
                    authorizations.c.id == authorization_id,
                    authorizations.c.tenant_id == identity.tenant_id,
                )
            ).first()
            if row is None:
                raise HTTPException(404, "authorization not found")
            if row.status == "ACTIVE":
                conn.execute(
                    authorizations.update()
                    .where(authorizations.c.id == authorization_id)
                    .values(status="REVOKED", revoked_at=now)
                )
                conn.execute(
                    audit.insert().values(
                        id=str(uuid.uuid4()),
                        tenant_id=identity.tenant_id,
                        actor_id=identity.actor_id,
                        action="customer_authorization.revoke",
                        resource=authorization_id,
                        correlation_id=authorization_id,
                        created_at=now,
                        details={"scope_digest": row.scope_digest},
                    )
                )
        return {"authorization_id": authorization_id, "status": "REVOKED"}

    @app.post("/v1/approvals", status_code=201)
    def create_approval(body: ApprovalRequest, identity: Principal) -> dict:
        require_operator(identity)
        if body.actor_id != identity.actor_id:
            raise HTTPException(403, "approval actor must be the authenticated operator")
        now, approval_id = time.time(), str(uuid.uuid4())
        payload_hash = digest(body.payload)
        with transaction(app.state.engine) as conn:
            conn.execute(
                approvals.insert().values(
                    id=approval_id,
                    tenant_id=identity.tenant_id,
                    actor_id=body.actor_id,
                    action=body.action,
                    resource=body.resource,
                    payload_digest=payload_hash,
                    expires_at=now + body.lifetime_seconds,
                    approved_by=identity.actor_id,
                    created_at=now,
                    used_at=None,
                )
            )
            conn.execute(
                audit.insert().values(
                    id=str(uuid.uuid4()),
                    tenant_id=identity.tenant_id,
                    actor_id=identity.actor_id,
                    action="approval.create",
                    resource=body.resource,
                    correlation_id=approval_id,
                    created_at=now,
                    details={
                        "approval_id": approval_id,
                        "action": body.action,
                        "payload_digest": payload_hash,
                        "expires_at": now + body.lifetime_seconds,
                    },
                )
            )
        return {
            "approval_id": approval_id,
            "payload_digest": payload_hash,
            "expires_at": now + body.lifetime_seconds,
        }

    @app.post("/v1/effects", status_code=202)
    def authorize_effect(body: EffectRequest, identity: Principal) -> dict:
        require_writer(identity)
        now, payload_hash = time.time(), digest(body.payload)
        with transaction(app.state.engine) as conn:
            previous = conn.execute(
                sa.select(outbox).where(
                    outbox.c.tenant_id == identity.tenant_id,
                    outbox.c.effect_key == body.effect_key,
                )
            ).first()
            if previous:
                if previous.payload_digest != payload_hash:
                    raise HTTPException(409, "effect key reused with a different payload")
                return {"outbox_id": previous.id, "status": previous.status, "dispatch_enabled": False}
            record = conn.execute(
                sa.select(approvals).where(
                    approvals.c.id == body.approval_id, approvals.c.tenant_id == identity.tenant_id
                )
            ).first()
            if record is None or record.used_at is not None or record.expires_at <= now:
                raise HTTPException(403, "approval missing, expired or already used")
            if (
                record.approved_by != identity.actor_id
                or record.actor_id != identity.actor_id
                or record.payload_digest != payload_hash
            ):
                raise HTTPException(403, "approval scope mismatch")
            outbox_id = str(uuid.uuid4())
            result = conn.execute(
                outbox.insert().values(
                    id=outbox_id,
                    tenant_id=identity.tenant_id,
                    actor_id=identity.actor_id,
                    job_id="approved-operator-action",
                    action=record.action,
                    resource=record.resource,
                    effect_key=body.effect_key,
                    payload_digest=payload_hash,
                    body=body.payload,
                    status="READY",
                    approval_reference=record.id,
                    created_at=now,
                    dispatched_at=None,
                )
            )
            if result.rowcount != 1:
                raise HTTPException(409, "effect key already used")
            conn.execute(approvals.update().where(approvals.c.id == record.id).values(used_at=now))
            conn.execute(
                audit.insert().values(
                    id=str(uuid.uuid4()),
                    tenant_id=identity.tenant_id,
                    actor_id=identity.actor_id,
                    action="effect.authorized",
                    resource=record.resource,
                    correlation_id=outbox_id,
                    created_at=now,
                    details={"action": record.action, "payload_digest": payload_hash, "outbox_id": outbox_id},
                )
            )
        return {"outbox_id": outbox_id, "status": "READY", "dispatch_enabled": False}

    @app.post("/v1/ledger", status_code=201)
    def record_ledger(body: LedgerRequest, identity: Principal) -> dict:
        require_operator(identity)
        if body.verified:
            raise HTTPException(
                422, "independent financial verification is unavailable; record as unverified"
            )
        values = body.model_dump()
        now = time.time()
        ident = str(uuid.uuid4())
        with transaction(app.state.engine) as conn:
            old = conn.execute(
                sa.select(ledger).where(
                    ledger.c.tenant_id == identity.tenant_id, ledger.c.event_key == body.event_key
                )
            ).first()
            payload_hash = digest(values)
            if old:
                if old.digest != payload_hash:
                    raise HTTPException(409, "ledger idempotency key reused with different entry")
                return {"entry_id": old.id, "created": False, "verified": old.body["verified"]}
            current_budget = conn.execute(
                sa.select(budgets).where(budgets.c.tenant_id == identity.tenant_id)
            ).first()
            if current_budget is None:
                conn.execute(
                    budgets.insert().values(
                        tenant_id=identity.tenant_id,
                        limit_micro_usd=settings.tenant_budget_micro_usd,
                        reserved_micro_usd=0,
                        spent_micro_usd=0,
                    )
                )
                current_budget = conn.execute(
                    sa.select(budgets).where(budgets.c.tenant_id == identity.tenant_id)
                ).one()
            if body.kind in {"llm_cost", "cloud_cost"} and (
                body.amount_micro_usd + current_budget.reserved_micro_usd + current_budget.spent_micro_usd
                > current_budget.limit_micro_usd
            ):
                raise HTTPException(409, "tenant budget exhausted")
            conn.execute(
                ledger.insert().values(
                    id=ident,
                    tenant_id=identity.tenant_id,
                    event_key=body.event_key,
                    kind=body.kind,
                    amount_micro_usd=body.amount_micro_usd,
                    source_reference=body.source_reference,
                    digest=payload_hash,
                    demo=body.demo,
                    occurred_at=now,
                    body=values,
                )
            )
            if body.kind in {"llm_cost", "cloud_cost"}:
                conn.execute(
                    budgets.update()
                    .where(budgets.c.tenant_id == identity.tenant_id)
                    .values(spent_micro_usd=current_budget.spent_micro_usd + body.amount_micro_usd)
                )
            conn.execute(
                audit.insert().values(
                    id=str(uuid.uuid4()),
                    tenant_id=identity.tenant_id,
                    actor_id=identity.actor_id,
                    action="ledger.record",
                    resource=ident,
                    correlation_id=body.event_key,
                    created_at=now,
                    details={"entry_digest": payload_hash, "demo": body.demo, "verified": body.verified},
                )
            )
        return {"entry_id": ident, "created": True, "verified": body.verified}

    @app.post("/v1/prospects", status_code=201)
    def add_prospect(body: ProspectRequest, identity: Principal) -> dict:
        require_writer(identity)
        domain = body.domain
        result = qualify(body)
        with transaction(app.state.engine) as conn:
            old = conn.execute(
                sa.select(prospects).where(
                    prospects.c.tenant_id == identity.tenant_id, prospects.c.domain == domain
                )
            ).first()
            if old:
                qualification = old.body.get("qualification", {})
                if "threshold" in qualification and (
                    qualification.get("criteria") != body.criteria
                    or qualification["threshold"] != body.qualification_threshold
                ):
                    raise HTTPException(409, "prospect domain already has different qualification inputs")
                return {
                    "prospect_id": old.id,
                    "created": False,
                    **old.body,
                    "domain": old.domain,
                    "stage": old.stage,
                    "outreach": "DISABLED",
                }
            ident = str(uuid.uuid4())
            conn.execute(
                prospects.insert().values(
                    id=ident,
                    tenant_id=identity.tenant_id,
                    domain=domain,
                    stage=result["stage"],
                    body=result,
                )
            )
        return {
            "prospect_id": ident,
            "created": True,
            **result,
        }

    @app.get("/v1/prospects")
    def list_prospects(identity: Principal) -> list[dict[str, Any]]:
        with app.state.engine.connect() as conn:
            rows = conn.execute(
                sa.select(prospects)
                .where(prospects.c.tenant_id == identity.tenant_id)
                .order_by(prospects.c.domain)
            ).all()
        return [
            {
                **row.body,
                "prospect_id": row.id,
                "domain": row.domain,
                "stage": row.stage,
                "outreach": "DISABLED",
            }
            for row in rows
        ]

    return app


def _job_view(row: Any) -> dict[str, Any]:
    return {
        "job_id": row.job_id,
        "tenant_id": row.tenant_id,
        "actor_id": row.actor_id,
        "job_type": row.job_type,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "maximum_attempts": row.maximum_attempts,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "completed_at": row.completed_at,
        "estimated_cost_micro_usd": row.estimated_cost,
        "actual_cost_micro_usd": row.actual_cost,
        "approval_reference": row.approval_reference,
        "evidence_reference": row.evidence_reference,
        "correlation_id": row.correlation_id,
        "error_code": row.error_code,
    }
