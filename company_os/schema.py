"""Immutable v1 tables. Future revisions must use explicit migrations."""

import sqlalchemy as sa

metadata = sa.MetaData()
control = sa.Table(
    "control",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("stopped", sa.Boolean, nullable=False),
)
budgets = sa.Table(
    "budgets",
    metadata,
    sa.Column("tenant_id", sa.String(128), primary_key=True),
    sa.Column("limit_micro_usd", sa.BigInteger, nullable=False),
    sa.Column("reserved_micro_usd", sa.BigInteger, nullable=False),
    sa.Column("spent_micro_usd", sa.BigInteger, nullable=False),
    sa.CheckConstraint("limit_micro_usd >= 0 AND reserved_micro_usd >= 0 AND spent_micro_usd >= 0"),
)
flags = sa.Table(
    "flags",
    metadata,
    sa.Column("tenant_id", sa.String(128), primary_key=True),
    sa.Column("key", sa.String(64), primary_key=True),
    sa.Column("enabled", sa.Boolean, nullable=False),
)
payloads = sa.Table(
    "payloads",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("body", sa.JSON, nullable=False),
)
jobs = sa.Table(
    "jobs",
    metadata,
    sa.Column("job_id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("job_type", sa.String(64), nullable=False),
    sa.Column("idempotency_key", sa.String(128), nullable=False),
    sa.Column("request_digest", sa.String(64), nullable=False),
    sa.Column("payload_reference", sa.String(64), sa.ForeignKey("payloads.id"), nullable=False),
    sa.Column("status", sa.String(32), nullable=False, index=True),
    sa.Column("attempt_count", sa.Integer, nullable=False),
    sa.Column("maximum_attempts", sa.Integer, nullable=False),
    sa.Column("lease_owner", sa.String(128)),
    sa.Column("lease_token", sa.String(64)),
    sa.Column("lease_expiration", sa.Float),
    sa.Column("available_at", sa.Float, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("updated_at", sa.Float, nullable=False),
    sa.Column("completed_at", sa.Float),
    sa.Column("estimated_cost", sa.BigInteger, nullable=False),
    sa.Column("actual_cost", sa.BigInteger, nullable=False),
    sa.Column("approval_reference", sa.String(64)),
    sa.Column("evidence_reference", sa.String(64)),
    sa.Column("correlation_id", sa.String(64), nullable=False),
    sa.Column("error_code", sa.String(64)),
    sa.UniqueConstraint("tenant_id", "idempotency_key"),
    sa.CheckConstraint(
        "attempt_count >= 0 AND maximum_attempts > 0 AND estimated_cost >= 0 AND actual_cost >= 0"
    ),
    sa.CheckConstraint(
        "status IN ('QUEUED','RUNNING','EVALUATING','RETRY_WAIT','WAITING_APPROVAL',"
        "'COMPLETED','FAILED','DEAD_LETTER','CANCELLED')"
    ),
)
events = sa.Table(
    "events",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("event_key", sa.String(128), nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.job_id"), nullable=False),
    sa.UniqueConstraint("tenant_id", "event_key"),
)
evidence = sa.Table(
    "evidence",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.job_id"), nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("body", sa.JSON, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.UniqueConstraint("job_id"),
)
evaluations = sa.Table(
    "evaluations",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("job_id", sa.String(64), nullable=False),
    sa.Column("version", sa.String(64), nullable=False),
    sa.Column("body", sa.JSON, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
)
approvals = sa.Table(
    "approvals",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("action", sa.String(64), nullable=False),
    sa.Column("resource", sa.String(256), nullable=False),
    sa.Column("payload_digest", sa.String(64), nullable=False),
    sa.Column("expires_at", sa.Float, nullable=False),
    sa.Column("approved_by", sa.String(128), nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("used_at", sa.Float),
)
audit = sa.Table(
    "audit",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("action", sa.String(64), nullable=False),
    sa.Column("resource", sa.String(256), nullable=False),
    sa.Column("correlation_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("details", sa.JSON, nullable=False),
)
outbox = sa.Table(
    "outbox",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("job_id", sa.String(64), nullable=False),
    sa.Column("action", sa.String(64), nullable=False),
    sa.Column("resource", sa.String(256), nullable=False),
    sa.Column("effect_key", sa.String(128), nullable=False),
    sa.Column("payload_digest", sa.String(64), nullable=False),
    sa.Column("body", sa.JSON, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("approval_reference", sa.String(64)),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("dispatched_at", sa.Float),
    sa.UniqueConstraint("tenant_id", "effect_key"),
)
ledger = sa.Table(
    "ledger",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("event_key", sa.String(128), nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("amount_micro_usd", sa.BigInteger, nullable=False),
    sa.Column("source_reference", sa.String(256), nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("demo", sa.Boolean, nullable=False),
    sa.Column("occurred_at", sa.Float, nullable=False),
    sa.Column("body", sa.JSON, nullable=False),
    sa.UniqueConstraint("tenant_id", "event_key"),
    sa.CheckConstraint("amount_micro_usd >= 0"),
)
prospects = sa.Table(
    "prospects",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("domain", sa.String(256), nullable=False),
    sa.Column("stage", sa.String(32), nullable=False),
    sa.Column("body", sa.JSON, nullable=False),
    sa.UniqueConstraint("tenant_id", "domain"),
)
authorizations = sa.Table(
    "authorizations",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
    sa.Column("repository", sa.String(160), nullable=False),
    sa.Column("customer_name", sa.String(256), nullable=False),
    sa.Column("signer_name", sa.String(256), nullable=False),
    sa.Column("window_start", sa.String(10), nullable=False),
    sa.Column("window_end", sa.String(10), nullable=False),
    sa.Column("authorization_digest", sa.String(64), nullable=False),
    sa.Column("scope_digest", sa.String(64), nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("authorized_at", sa.Float, nullable=False),
    sa.Column("expires_at", sa.Float, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("revoked_at", sa.Float),
    sa.CheckConstraint("window_start <= window_end"),
    sa.CheckConstraint("status IN ('ACTIVE','REVOKED')"),
)
schedules = sa.Table(
    "schedules",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(128), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("job_type", sa.String(64), nullable=False),
    sa.Column("body", sa.JSON, nullable=False),
    sa.Column("interval_seconds", sa.Integer, nullable=False),
    sa.Column("next_at", sa.Float, nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False),
)
