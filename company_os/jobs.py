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
from company_os.schema import budgets, control, events, evidence, flags, jobs, payloads
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
    pass


@dataclass(frozen=True)
class Submission:
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
    engine: Engine, task: dict, error: str, maximum_delay: int = 3600, *, now: float | None = None
) -> bool:
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
        dead = row.attempt_count >= row.maximum_attempts
        raw = min(maximum_delay, 2 ** min(row.attempt_count, 10))
        jitter = int(digest([row.job_id, row.attempt_count])[:4], 16) % max(1, raw // 4 + 1)
        conn.execute(
            jobs.update()
            .where(jobs.c.job_id == row.job_id)
            .values(
                status="DEAD_LETTER" if dead else "RETRY_WAIT",
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
