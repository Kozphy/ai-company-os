"""Transactional tenant queue; effects at least once, fenced and idempotent."""

import json
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from company_os.db import transaction
from company_os.schema import approvals, budgets, control, events, evidence, flags, jobs, payloads
from company_os.security import digest, redact

STATUSES = {
    "QUEUED",
    "RUNNING",
    "EVALUATING",
    "RETRY_WAIT",
    "WAITING_APPROVAL",
    "COMPLETED",
    "FAILED",
    "DEAD_LETTER",
    "CANCELLED",
}
JOB_TYPES = {"engineering", "research", "sales", "delivery", "finance"}
JOB_COST_MICRO_USD = {kind: 0 for kind in JOB_TYPES}  # no provider adapters are enabled


class Conflict(Exception):
    """The queue rejected the request because of a kill switch, replay, or budget."""


@dataclass(frozen=True)
class Submission:
    """Result of an idempotent job submission.

    Attributes:
        job_id: New or existing job identifier.
        status: Current job status.
        created: ``True`` when this call inserted the job.
    """

    job_id: str
    status: str
    created: bool


def submit(
    engine: Engine,
    *,
    tenant: str,
    actor: str,
    kind: str,
    key: str,
    payload: dict[str, Any],
    budget_limit: int,
    maximum_attempts: int = 3,
    event_key: str | None = None,
    now: float | None = None,
) -> Submission:
    """Queue a tenant job or return the job already stored for the same request.

    Payload secrets are redacted before persistence. A matching idempotency
    key or event key returns the existing job. A reused key with different
    content is a conflict. The estimated provider cost is zero because no
    provider adapter is enabled; that zero is still reserved against the
    tenant budget.

    Args:
        engine: Database engine.
        tenant: Tenant that owns the job.
        actor: Actor recorded on the job.
        kind: One of the five workflow names.
        key: Tenant-scoped idempotency key, 1 to 128 characters.
        payload: JSON-compatible job input. It is redacted before it is stored.
        budget_limit: Budget created for the tenant when none exists.
        maximum_attempts: Attempts allowed before dead-letter. Defaults to 3.
        event_key: Optional second idempotency key, used by webhook delivery ids.
        now: Unix timestamp for ``available_at``. Defaults to the current time.

    Returns:
        The new or existing submission.

    Raises:
        ValueError: The kind, key, attempt limit, or payload is invalid, or
            the redacted JSON exceeds 1,000,000 characters.
        Conflict: A kill switch is active, a key was replayed with different
            content, or the tenant budget is exhausted.
    """
    if kind not in JOB_TYPES or not key or len(key) > 128 or not 1 <= maximum_attempts <= 8:
        raise ValueError("invalid job request")
    redacted_payload = redact(payload)
    if not isinstance(redacted_payload, dict):
        raise ValueError("invalid job payload")
    payload = redacted_payload
    if len(json.dumps(payload, ensure_ascii=False)) > 1_000_000:
        raise ValueError("payload too large")
    now = time.time() if now is None else now
    request_hash = digest({"kind": kind, "payload": payload})
    cost = JOB_COST_MICRO_USD[kind]
    jid, pid, cid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with transaction(engine) as conn:
        if conn.execute(sa.select(control.c.stopped).where(control.c.id == 1)).scalar_one():
            raise Conflict("global kill switch is active")
        stopped = conn.execute(
            sa.select(flags.c.enabled).where(flags.c.tenant_id == tenant, flags.c.key == "kill_switch")
        ).first()
        if stopped and stopped.enabled:
            raise Conflict("tenant kill switch is active")
        if event_key:
            old_event = conn.execute(
                sa.select(events).where(events.c.tenant_id == tenant, events.c.event_key == event_key)
            ).first()
            if old_event:
                if old_event.digest != request_hash:
                    raise Conflict("event identifier replayed with a different payload")
                row = conn.execute(sa.select(jobs).where(jobs.c.job_id == old_event.job_id)).one()
                return Submission(row.job_id, row.status, False)
        existing = conn.execute(
            sa.select(jobs).where(jobs.c.tenant_id == tenant, jobs.c.idempotency_key == key)
        ).first()
        if existing:
            if existing.request_digest != request_hash:
                raise Conflict("idempotency key replayed with a different payload")
            if event_key:
                conn.execute(
                    events.insert().values(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant,
                        event_key=event_key,
                        digest=request_hash,
                        job_id=existing.job_id,
                    )
                )
            return Submission(existing.job_id, existing.status, False)
        budget = conn.execute(sa.select(budgets).where(budgets.c.tenant_id == tenant)).first()
        if budget is None:
            conn.execute(
                budgets.insert().values(
                    tenant_id=tenant, limit_micro_usd=budget_limit, reserved_micro_usd=0, spent_micro_usd=0
                )
            )
            budget = conn.execute(sa.select(budgets).where(budgets.c.tenant_id == tenant)).one()
        if cost + budget.reserved_micro_usd + budget.spent_micro_usd > budget.limit_micro_usd:
            raise Conflict("tenant budget exhausted")
        conn.execute(
            budgets.update()
            .where(budgets.c.tenant_id == tenant)
            .values(reserved_micro_usd=budget.reserved_micro_usd + cost)
        )
        conn.execute(payloads.insert().values(id=pid, tenant_id=tenant, digest=digest(payload), body=payload))
        conn.execute(
            jobs.insert().values(
                job_id=jid,
                tenant_id=tenant,
                actor_id=actor,
                job_type=kind,
                idempotency_key=key,
                request_digest=request_hash,
                payload_reference=pid,
                status="QUEUED",
                attempt_count=0,
                maximum_attempts=maximum_attempts,
                lease_owner=None,
                lease_token=None,
                lease_expiration=None,
                available_at=now,
                created_at=now,
                updated_at=now,
                completed_at=None,
                estimated_cost=cost,
                actual_cost=0,
                approval_reference=None,
                evidence_reference=None,
                correlation_id=cid,
                error_code=None,
            )
        )
        if event_key:
            conn.execute(
                events.insert().values(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant,
                    event_key=event_key,
                    digest=request_hash,
                    job_id=jid,
                )
            )
        return Submission(jid, "QUEUED", True)


def claim(engine: Engine, owner: str, lease_seconds: int, *, now: float | None = None) -> dict | None:
    """Lease the oldest due job and recover leases that have already expired.

    Expired ``RUNNING`` and ``EVALUATING`` jobs return to ``RETRY_WAIT``, or
    move to ``DEAD_LETTER`` when attempts are exhausted. Dead-letter releases
    the reserved budget. Tenants with an enabled kill switch are skipped.
    The global kill switch returns no work.

    Args:
        engine: Database engine.
        owner: Worker id written onto the lease.
        lease_seconds: How long the new lease lasts.
        now: Unix timestamp. Defaults to the current time.

    Returns:
        The claimed job row plus its payload and lease token, or ``None``
        when no job is due or the claim lost a race.
    """
    now = time.time() if now is None else now
    with transaction(engine) as conn:
        if conn.execute(sa.select(control.c.stopped).where(control.c.id == 1)).scalar_one():
            return None
        stale = conn.execute(
            sa.select(jobs).where(
                jobs.c.status.in_(["RUNNING", "EVALUATING"]), jobs.c.lease_expiration <= now
            )
        ).all()
        for old in stale:
            dead = old.attempt_count >= old.maximum_attempts
            delay = min(3600, 2 ** max(0, old.attempt_count - 1))
            delay += int(digest([old.job_id, old.attempt_count, "lease"])[:4], 16) % max(
                1, delay // 4 + 1
            )
            conn.execute(
                jobs.update()
                .where(jobs.c.job_id == old.job_id)
                .values(
                    status="DEAD_LETTER" if dead else "RETRY_WAIT",
                    lease_owner=None,
                    lease_token=None,
                    lease_expiration=None,
                    available_at=now + delay,
                    updated_at=now,
                    error_code="lease_expired",
                )
            )
            if dead:
                conn.execute(
                    budgets.update()
                    .where(budgets.c.tenant_id == old.tenant_id)
                    .values(reserved_micro_usd=budgets.c.reserved_micro_usd - old.estimated_cost)
                )
        due = conn.execute(
            sa.select(jobs)
            .where(
                jobs.c.status.in_(["QUEUED", "RETRY_WAIT"]),
                jobs.c.available_at <= now,
                ~sa.exists(
                    sa.select(flags.c.tenant_id).where(
                        flags.c.tenant_id == jobs.c.tenant_id,
                        flags.c.key == "kill_switch",
                        flags.c.enabled.is_(True),
                    )
                ),
            )
            .order_by(jobs.c.created_at)
            .limit(1)
        ).first()
        if due is None:
            return None
        token = secrets.token_hex(32)
        result = conn.execute(
            jobs.update()
            .where(jobs.c.job_id == due.job_id, jobs.c.status == due.status)
            .values(
                status="RUNNING",
                attempt_count=due.attempt_count + 1,
                lease_owner=owner,
                lease_token=token,
                lease_expiration=now + lease_seconds,
                updated_at=now,
            )
            .returning(jobs.c.job_id)
        )
        if result.first() is None:
            return None
        task = conn.execute(
            sa.select(jobs, payloads.c.body.label("payload"))
            .join(payloads, payloads.c.id == jobs.c.payload_reference)
            .where(jobs.c.job_id == due.job_id)
        ).one()
        return {**task._mapping, "lease_token": token}


def heartbeat(
    engine: Engine, job_id: str, token: str, lease_seconds: int, *, now: float | None = None
) -> bool:
    """Extend a live ``RUNNING`` or ``EVALUATING`` lease.

    Args:
        engine: Database engine.
        job_id: Job to extend.
        token: Lease token from ``claim``.
        lease_seconds: New lease length measured from ``now``.
        now: Unix timestamp. Defaults to the current time.

    Returns:
        ``True`` when the lease was extended. ``False`` when the token, status,
        or expiry does not match.
    """
    now = time.time() if now is None else now
    with transaction(engine) as conn:
        result = conn.execute(
            jobs.update()
            .where(
                jobs.c.job_id == job_id,
                jobs.c.lease_token == token,
                jobs.c.status.in_(["RUNNING", "EVALUATING"]),
                jobs.c.lease_expiration > now,
            )
            .values(lease_expiration=now + lease_seconds, updated_at=now)
        )
        return result.rowcount == 1


def start_evaluation(engine: Engine, task: dict, *, now: float | None = None) -> bool:
    """Move a leased running job to ``EVALUATING``.

    Args:
        engine: Database engine.
        task: Claimed job mapping. ``job_id``, ``tenant_id``, and
            ``lease_token`` must match the live row.
        now: Unix timestamp. Defaults to the current time.

    Returns:
        ``True`` when the status changed. ``False`` when the lease no longer
        matches.
    """
    now = time.time() if now is None else now
    with transaction(engine) as conn:
        result = conn.execute(
            jobs.update()
            .where(
                jobs.c.job_id == task["job_id"],
                jobs.c.tenant_id == task["tenant_id"],
                jobs.c.status == "RUNNING",
                jobs.c.lease_token == task["lease_token"],
                jobs.c.lease_expiration > now,
            )
            .values(status="EVALUATING", updated_at=now)
        )
        return result.rowcount == 1


def finish(engine: Engine, task: dict, body: dict, *, now: float | None = None) -> bool:
    """Store the job report and mark a leased evaluating job completed.

    The reserved estimate is released. Recorded actual cost is zero.

    Args:
        engine: Database engine.
        task: Claimed job mapping with a live evaluating lease.
        body: Report stored as the job's only evidence row.
        now: Unix timestamp. Defaults to the current time.

    Returns:
        ``True`` when evidence was stored and the job completed. ``False``
        when the lease no longer matches.
    """
    now = time.time() if now is None else now
    report_id = str(uuid.uuid4())
    with transaction(engine) as conn:
        row = conn.execute(
            sa.select(jobs).where(
                jobs.c.job_id == task["job_id"],
                jobs.c.tenant_id == task["tenant_id"],
                jobs.c.status == "EVALUATING",
                jobs.c.lease_token == task["lease_token"],
                jobs.c.lease_expiration > now,
            )
        ).first()
        if row is None:
            return False
        conn.execute(
            evidence.insert().values(
                id=report_id,
                tenant_id=row.tenant_id,
                job_id=row.job_id,
                digest=digest(body),
                body=body,
                created_at=now,
            )
        )
        conn.execute(
            jobs.update()
            .where(jobs.c.job_id == row.job_id)
            .values(
                status="COMPLETED",
                evidence_reference=report_id,
                completed_at=now,
                updated_at=now,
                lease_owner=None,
                lease_token=None,
                lease_expiration=None,
                actual_cost=0,
            )
        )
        conn.execute(
            budgets.update()
            .where(budgets.c.tenant_id == row.tenant_id)
            .values(
                reserved_micro_usd=budgets.c.reserved_micro_usd - row.estimated_cost,
                spent_micro_usd=budgets.c.spent_micro_usd + 0,
            )
        )
        return True


def fail(
    engine: Engine,
    task: dict,
    error: str,
    maximum_delay: int = 3600,
    *,
    now: float | None = None,
    permanent: bool = False,
) -> bool:
    """Retry a leased job or terminate it and release its reservation.

    Retry delay doubles with the attempt count, up to ``maximum_delay``, and
    adds a deterministic jitter derived from the job id.

    Args:
        engine: Database engine.
        task: Claimed job mapping. The lease token must still be valid.
        error: Error code stored on the job, truncated to 64 characters.
        maximum_delay: Cap on the retry backoff in seconds.
        now: Unix timestamp. Defaults to the current time.
        permanent: When true, mark the job ``FAILED`` immediately. Otherwise
            exhausted attempts become ``DEAD_LETTER``.

    Returns:
        ``True`` when the job was updated. ``False`` when the lease no longer
        matches.
    """
    now = time.time() if now is None else now
    with transaction(engine) as conn:
        row = conn.execute(
            sa.select(jobs).where(
                jobs.c.job_id == task["job_id"],
                jobs.c.status.in_(["RUNNING", "EVALUATING"]),
                jobs.c.lease_token == task["lease_token"],
                jobs.c.lease_expiration > now,
            )
        ).first()
        if row is None:
            return False
        dead = permanent or row.attempt_count >= row.maximum_attempts
        terminal_status = "FAILED" if permanent else "DEAD_LETTER"
        raw = min(maximum_delay, 2 ** min(row.attempt_count, 10))
        jitter = int(digest([row.job_id, row.attempt_count])[:4], 16) % max(1, raw // 4 + 1)
        conn.execute(
            jobs.update()
            .where(jobs.c.job_id == row.job_id)
            .values(
                status=terminal_status if dead else "RETRY_WAIT",
                available_at=now + raw + jitter,
                updated_at=now,
                error_code=error[:64],
                lease_owner=None,
                lease_token=None,
                lease_expiration=None,
                completed_at=now if dead else None,
            )
        )
        if dead:
            conn.execute(
                budgets.update()
                .where(budgets.c.tenant_id == row.tenant_id)
                .values(reserved_micro_usd=budgets.c.reserved_micro_usd - row.estimated_cost)
            )
        return True


def cancel(engine: Engine, tenant: str, job_id: str, *, now: float | None = None) -> bool:
    """Cancel a job that has not started or is waiting, and release its reservation.

    Args:
        engine: Database engine.
        tenant: Tenant that must own the job.
        job_id: Job to cancel.
        now: Unix timestamp. Defaults to the current time.

    Returns:
        ``True`` when a queued, retrying, or approval-waiting job was
        cancelled. ``False`` when the job is missing or already active or
        terminal.
    """
    now = time.time() if now is None else now
    with transaction(engine) as conn:
        row = conn.execute(sa.select(jobs).where(jobs.c.tenant_id == tenant, jobs.c.job_id == job_id)).first()
        if row is None:
            return False
        if row.status not in {"QUEUED", "RETRY_WAIT", "WAITING_APPROVAL"}:
            return False
        conn.execute(
            jobs.update()
            .where(jobs.c.job_id == job_id)
            .values(status="CANCELLED", updated_at=now, completed_at=now)
        )
        conn.execute(
            budgets.update()
            .where(budgets.c.tenant_id == tenant)
            .values(reserved_micro_usd=budgets.c.reserved_micro_usd - row.estimated_cost)
        )
        return True


def hold_for_approval(
    engine: Engine,
    task: dict[str, Any],
    reason: str,
    *,
    now: float | None = None,
) -> bool:
    """Transition a leased running job to WAITING_APPROVAL.

    The lease is cleared and the job waits until an authorized operator
    approves it via ``approve_job``.

    Args:
        engine: Database engine.
        task: Leased task dict containing ``job_id`` and ``lease_token``.
        reason: Explanatory error code or review reason.
        now: Unix timestamp. Defaults to current time.

    Returns:
        ``True`` when the leased job was successfully placed on hold.
        ``False`` if the lease was lost or the job is not RUNNING.
    """
    now = time.time() if now is None else now
    with transaction(engine) as conn:
        result = conn.execute(
            jobs.update()
            .where(
                jobs.c.job_id == task["job_id"],
                jobs.c.lease_token == task["lease_token"],
                jobs.c.status == "RUNNING",
            )
            .values(
                status="WAITING_APPROVAL",
                error_code=reason[:64],
                lease_owner=None,
                lease_token=None,
                lease_expiration=None,
                updated_at=now,
            )
        )
        return result.rowcount == 1


def approve_job(
    engine: Engine,
    tenant: str,
    job_id: str,
    operator_id: str,
    approval_id: str,
    *,
    now: float | None = None,
) -> bool:
    """Approve a WAITING_APPROVAL job using an active, unexpired approval record.

    Verifies that the approval belongs to ``tenant``, has not expired,
    has not been used (``used_at IS NULL``), and matches ``approval_id``.
    Transitions the job from WAITING_APPROVAL to QUEUED and binds
    ``approval_reference`` on the job.

    Args:
        engine: Database engine.
        tenant: Tenant identifier.
        job_id: Job identifier to approve.
        operator_id: Operator issuing the approval.
        approval_id: Existing record id in the approvals table.
        now: Unix timestamp. Defaults to current time.

    Returns:
        ``True`` when the job was successfully approved and queued.

    Raises:
        Conflict: The approval is missing, expired, already used, or
            the job is not in WAITING_APPROVAL status.
    """
    now = time.time() if now is None else now
    with transaction(engine) as conn:
        record = conn.execute(
            sa.select(approvals).where(
                approvals.c.id == approval_id,
                approvals.c.tenant_id == tenant,
            )
        ).first()
        if record is None or record.used_at is not None or record.expires_at <= now:
            raise Conflict("approval_missing_expired_or_used")
        job = conn.execute(
            sa.select(jobs).where(
                jobs.c.job_id == job_id,
                jobs.c.tenant_id == tenant,
            )
        ).first()
        if job is None or job.status != "WAITING_APPROVAL":
            raise Conflict("job_not_waiting_approval")
        conn.execute(
            approvals.update().where(approvals.c.id == approval_id).values(used_at=now)
        )
        result = conn.execute(
            jobs.update()
            .where(
                jobs.c.job_id == job_id,
                jobs.c.tenant_id == tenant,
                jobs.c.status == "WAITING_APPROVAL",
            )
            .values(
                status="QUEUED",
                approval_reference=approval_id,
                error_code=None,
                available_at=now,
                updated_at=now,
            )
        )
        return result.rowcount == 1
