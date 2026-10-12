"""Fail-closed tenant authorization scope checks for audit exports and delivery."""

import time
from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from company_os.schema import authorizations


class AuthorizationError(ValueError):
    pass


def validate_scope(
    engine: Engine,
    *,
    tenant_id: str,
    authorization_id: object,
    repository: object,
    window_start: object,
    window_end: object,
    now: float | None = None,
) -> dict[str, str]:
    moment = time.time() if now is None else now
    if not isinstance(authorization_id, str) or not authorization_id:
        raise AuthorizationError("customer_authorization_required")
    try:
        actual_start = date.fromisoformat(str(window_start)[:10])
        actual_end = date.fromisoformat(str(window_end)[:10])
    except ValueError as exc:
        raise AuthorizationError("audit_window_invalid") from exc
    with engine.connect() as conn:
        record = conn.execute(
            sa.select(authorizations).where(
                authorizations.c.id == authorization_id,
                authorizations.c.tenant_id == tenant_id,
                authorizations.c.status == "ACTIVE",
                authorizations.c.expires_at > moment,
            )
        ).first()
    if (
        record is None
        or repository != record.repository
        or actual_start < date.fromisoformat(record.window_start)
        or actual_end > date.fromisoformat(record.window_end)
    ):
        raise AuthorizationError("customer_authorization_scope_mismatch")
    return {"authorization_id": record.id, "scope_digest": record.scope_digest}


def validate_export(
    engine: Engine, tenant_id: str, payload: dict[str, Any], *, now: float | None = None
) -> dict[str, str]:
    export = payload.get("export")
    if not isinstance(export, dict):
        raise AuthorizationError("engineering_export_required")
    return validate_scope(
        engine,
        tenant_id=tenant_id,
        authorization_id=payload.get("authorization_reference"),
        repository=export.get("repository"),
        window_start=export.get("since"),
        window_end=export.get("collected_at"),
        now=now,
    )
