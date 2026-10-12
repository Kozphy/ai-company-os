"""Fail-closed tenant authorization scope checks for audit exports and delivery."""

import time
from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from company_os.schema import authorizations


class AuthorizationError(ValueError):
    """The customer authorization is missing, expired, or outside its scope."""


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
    """Require an active authorization that covers this repository and window.

    The record must belong to ``tenant_id``, have status ``ACTIVE``, and
    expire after ``now``. The repository must match exactly. The requested
    dates must fall inside the stored window.

    Args:
        engine: Database engine that stores authorizations.
        tenant_id: Tenant that owns the authorization.
        authorization_id: Stored authorization identifier.
        repository: Repository the work will read, as ``owner/name``.
        window_start: Inclusive start of the requested window. The first ten
            characters must be an ISO date.
        window_end: Inclusive end of the requested window. The first ten
            characters must be an ISO date.
        now: Unix timestamp used for expiry. Defaults to the current time.

    Returns:
        The authorization id and the stored scope digest.

    Raises:
        AuthorizationError: The id, dates, tenant, repository, window, or
            expiry do not match an active record.
    """
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
    """Check an engineering export against the referenced customer authorization.

    Args:
        engine: Database engine that stores authorizations.
        tenant_id: Tenant submitting the export.
        payload: Job payload containing ``export`` and
            ``authorization_reference``.
        now: Unix timestamp used for expiry. Defaults to the current time.

    Returns:
        The authorization id and scope digest from ``validate_scope``.

    Raises:
        AuthorizationError: ``export`` is missing or the referenced
            authorization does not cover the export repository and dates.
    """
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
