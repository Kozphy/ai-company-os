"""Bearer-token identities and payload redaction for the local API."""

import hashlib
import json
import re
from dataclasses import dataclass

from fastapi import HTTPException, Request

_SECRET_PATTERNS = (
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~-]+"),
    re.compile(r"(?i)((?:password|secret|token|api[_-]?key)\s*[:=]\s*[\"']?)[^,\s\"']+"),
)


def redact(value: object) -> object:
    """Remove common credential forms before task payloads are persisted.

    Matching text is replaced with ``[REDACTED]`` while a recognized label
    such as ``password=`` is kept. Dicts and lists are walked recursively.
    Other types are returned unchanged.

    Args:
        value: JSON-like value to redact.

    Returns:
        A redacted copy of ``value``.
    """
    if isinstance(value, str):
        result = value
        for pattern in _SECRET_PATTERNS:
            result = pattern.sub(
                lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]",
                result,
            )
        return result
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def digest(body: object) -> str:
    """Hash a JSON-compatible value with stable key order.

    Args:
        body: Value accepted by ``json.dumps`` with ``allow_nan=False``.

    Returns:
        Lowercase SHA-256 hex digest of the compact UTF-8 JSON.

    Raises:
        TypeError: ``body`` contains a value JSON cannot encode.
        ValueError: ``body`` contains NaN or infinity.
    """
    data = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


@dataclass(frozen=True)
class Identity:
    """Authenticated caller.

    Attributes:
        tenant_id: Tenant the token is allowed to access.
        actor_id: Stable actor name stored on writes.
        role: ``operator``, ``member``, or ``reader``.
    """

    tenant_id: str
    actor_id: str
    role: str


def authenticate(request: Request) -> Identity:
    """Resolve a bearer token to a configured identity.

    The raw token is hashed before lookup and is not retained.

    Args:
        request: Incoming request. Its app settings supply the identity map.

    Returns:
        The identity stored under the token's SHA-256 hash.

    Raises:
        HTTPException: The header is missing or the hash is unknown. Status
            is 401.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "authentication required")
    token_hash = hashlib.sha256(header[7:].encode()).hexdigest()
    entry = json.loads(request.app.state.settings.identities_json).get(token_hash)
    if entry is None:
        raise HTTPException(401, "invalid credential")
    return Identity(**entry)


def require_writer(identity: Identity) -> None:
    """Allow operators and members to write.

    Args:
        identity: Authenticated caller.

    Raises:
        HTTPException: The role is ``reader``. Status is 403.
    """
    if identity.role not in {"operator", "member"}:
        raise HTTPException(403, "write permission required")


def require_operator(identity: Identity) -> None:
    """Allow only operators.

    Args:
        identity: Authenticated caller.

    Raises:
        HTTPException: The role is not ``operator``. Status is 403.
    """
    if identity.role != "operator":
        raise HTTPException(403, "operator permission required")
