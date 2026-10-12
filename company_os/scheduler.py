"""SQL-backed interval scheduler. Advancing a tick is replay-safe by job idempotency key."""

import time

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from company_os.db import transaction
from company_os.jobs import Conflict, submit
from company_os.schema import schedules


class Scheduler:
    """Submit one job per due schedule tick.

    Each tick uses the idempotency key ``schedule:{id}:{scheduled_at}``. A
    repeated tick therefore returns the existing job. A tenant kill switch
    skips submission and still advances the schedule. Any other submit
    conflict is raised.
    """

    def __init__(self, engine: Engine, budget_limit: int):
        """Bind the scheduler to a database and a default tenant budget.

        Args:
            engine: Database engine.
            budget_limit: Budget applied when a tenant has no budget row yet.
        """
        self.engine = engine
        self.budget_limit = budget_limit

    def run_once(self, *, now: float | None = None) -> int:
        """Submit every schedule that is due at ``now``.

        Args:
            now: Unix timestamp. Defaults to the current time.

        Returns:
            The number of due ticks advanced.

        Raises:
            Conflict: Submission failed for a reason other than a kill switch.
        """
        current = time.time() if now is None else now
        count = 0
        while True:
            with transaction(self.engine) as conn:
                due = conn.execute(
                    sa.select(schedules)
                    .where(schedules.c.enabled.is_(True), schedules.c.next_at <= current)
                    .order_by(schedules.c.next_at)
                    .limit(1)
                ).first()
            if due is None:
                return count
            scheduled_at = due.next_at
            key = f"schedule:{due.id}:{int(scheduled_at)}"
            try:
                submit(
                    self.engine,
                    tenant=due.tenant_id,
                    actor=due.actor_id,
                    kind=due.job_type,
                    key=key,
                    payload=due.body,
                    budget_limit=self.budget_limit,
                )
            except Conflict as exc:
                if "kill switch" not in str(exc):
                    raise
            next_at = (
                scheduled_at
                + (int((current - scheduled_at) // due.interval_seconds) + 1) * due.interval_seconds
            )
            with transaction(self.engine) as conn:
                conn.execute(
                    schedules.update()
                    .where(schedules.c.id == due.id, schedules.c.next_at == scheduled_at)
                    .values(next_at=next_at)
                )
            count += 1

    def run_forever(self, poll_seconds: float = 15.0) -> None:
        """Poll ``run_once`` until the process is stopped.

        Args:
            poll_seconds: Delay between polls. ``run_once`` still drains every
                tick that is already due before sleeping.
        """
        while True:
            self.run_once()
            time.sleep(poll_seconds)
