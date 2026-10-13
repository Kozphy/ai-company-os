"""Offline deliverable packaging, immutable report review, and integrity verification."""

import hashlib
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from company_os.security import digest


class DeliverableInput(BaseModel):
    """Input parameters for packaging a deliverable from a completed job.

    Attributes:
        report_title: Short title for the deliverable report.
        report_markdown: Optional markdown content; inferred from evidence if omitted.
        evidence_reference: Optional backing evidence ID; inferred from job if omitted.
        authorization_reference: Optional customer authorization reference.
    """

    model_config = ConfigDict(extra="forbid")
    report_title: str = Field(default="Delivery Report", min_length=1, max_length=128)
    report_markdown: str | None = Field(default=None, max_length=1_000_000)
    evidence_reference: str | None = Field(default=None, max_length=64)
    authorization_reference: str | None = Field(default=None, max_length=64)


class ReviewSignoffInput(BaseModel):
    """Operator sign-off or rejection of a deliverable report.

    Attributes:
        status: Target review status, either ``SIGNED_OFF`` or ``REJECTED``.
        notes: Optional operator review notes.
    """

    model_config = ConfigDict(extra="forbid")
    status: Literal["SIGNED_OFF", "REJECTED"]
    notes: str | None = Field(default=None, max_length=1000)


class DeliverablePackage(BaseModel):
    """Immutable local deliverable package with cryptographic verification.

    Attributes:
        package_id: Unique identifier for this package.
        tenant_id: Tenant that owns this deliverable.
        job_id: Job identifier that generated the report or evidence.
        created_at: Unix timestamp when the package was assembled.
        report_title: Title of the deliverable report.
        report_markdown: Markdown body of the report.
        report_sha256: Hex-encoded SHA-256 digest of ``report_markdown``.
        evidence_reference: Stored evidence record identifier.
        evidence_digest: Stored digest of the backing evidence.
        evidence_status: Provenance status of the evidence.
        authorization_reference: Covering customer authorization if applicable.
        authorization_scope_digest: Covering scope digest if applicable.
        authorization_status: Authorization state at assembly time.
        review_status: Human sign-off lifecycle state.
        reviewed_by: Operator actor ID who signed off, or ``None``.
        reviewed_at: Unix timestamp of operator sign-off, or ``None``.
        review_notes: Operator notes recorded at sign-off, or ``None``.
        manifest_digest: SHA-256 digest over the canonical package manifest.
        external_delivery: Always ``DISABLED``. External transmission is not supported.
        communication: Always ``DISABLED``. No outbound messaging or email.
    """

    model_config = ConfigDict(extra="forbid")
    package_id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(min_length=1, max_length=64)
    created_at: float
    report_title: str = Field(min_length=1, max_length=128)
    report_markdown: str = Field(min_length=1, max_length=1_000_000)
    report_sha256: str = Field(min_length=64, max_length=64)
    evidence_reference: str = Field(min_length=1, max_length=64)
    evidence_digest: str = Field(min_length=1, max_length=64)
    evidence_status: str = Field(min_length=1, max_length=64)
    authorization_reference: str | None = Field(default=None, max_length=64)
    authorization_scope_digest: str | None = Field(default=None, max_length=64)
    authorization_status: str = Field(default="UNSPECIFIED", min_length=1, max_length=64)
    review_status: Literal["AWAITING_HUMAN_SIGNOFF", "SIGNED_OFF", "REJECTED"] = "AWAITING_HUMAN_SIGNOFF"
    reviewed_by: str | None = Field(default=None, max_length=128)
    reviewed_at: float | None = None
    review_notes: str | None = Field(default=None, max_length=1000)
    manifest_digest: str = Field(min_length=64, max_length=64)
    external_delivery: Literal["DISABLED"] = "DISABLED"
    communication: Literal["DISABLED"] = "DISABLED"


def compute_manifest_digest(data: dict[str, Any]) -> str:
    """Calculate the canonical SHA-256 digest over manifest fields.

    Args:
        data: Package mapping. The ``manifest_digest`` field itself is excluded.

    Returns:
        The lowercase SHA-256 hex digest of the canonical JSON representation.
    """
    manifest_fields = {
        "package_id": data.get("package_id"),
        "tenant_id": data.get("tenant_id"),
        "job_id": data.get("job_id"),
        "created_at": data.get("created_at"),
        "report_title": data.get("report_title"),
        "report_sha256": data.get("report_sha256"),
        "evidence_reference": data.get("evidence_reference"),
        "evidence_digest": data.get("evidence_digest"),
        "evidence_status": data.get("evidence_status"),
        "authorization_reference": data.get("authorization_reference"),
        "authorization_scope_digest": data.get("authorization_scope_digest"),
        "authorization_status": data.get("authorization_status"),
        "review_status": data.get("review_status"),
        "reviewed_by": data.get("reviewed_by"),
        "reviewed_at": data.get("reviewed_at"),
        "review_notes": data.get("review_notes"),
        "external_delivery": "DISABLED",
        "communication": "DISABLED",
    }
    return digest(manifest_fields)


def build_package(
    *,
    tenant_id: str,
    job_id: str,
    report_title: str,
    report_markdown: str,
    evidence_reference: str,
    evidence_digest: str,
    evidence_status: str,
    authorization_reference: str | None = None,
    authorization_scope_digest: str | None = None,
    authorization_status: str = "UNSPECIFIED",
    package_id: str | None = None,
    created_at: float | None = None,
) -> DeliverablePackage:
    """Assemble an immutable local deliverable package awaiting sign-off.

    Args:
        tenant_id: Tenant owning the deliverable.
        job_id: Completed job identifier.
        report_title: Title for the deliverable report.
        report_markdown: Markdown body of the report.
        evidence_reference: Identifier of backing evidence.
        evidence_digest: Cryptographic digest of backing evidence.
        evidence_status: Provenance status of evidence.
        authorization_reference: Optional customer authorization ID.
        authorization_scope_digest: Optional customer authorization scope digest.
        authorization_status: State of customer authorization.
        package_id: Optional explicit package ID; defaults to a new UUID.
        created_at: Optional assembly timestamp; defaults to current time.

    Returns:
        A validated ``DeliverablePackage`` ready for human review.
    """
    pid = package_id or str(uuid.uuid4())
    now = time.time() if created_at is None else created_at
    report_sha256 = hashlib.sha256(report_markdown.encode("utf-8")).hexdigest()
    fields: dict[str, Any] = {
        "package_id": pid,
        "tenant_id": tenant_id,
        "job_id": job_id,
        "created_at": now,
        "report_title": report_title,
        "report_markdown": report_markdown,
        "report_sha256": report_sha256,
        "evidence_reference": evidence_reference,
        "evidence_digest": evidence_digest,
        "evidence_status": evidence_status,
        "authorization_reference": authorization_reference,
        "authorization_scope_digest": authorization_scope_digest,
        "authorization_status": authorization_status,
        "review_status": "AWAITING_HUMAN_SIGNOFF",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_notes": None,
        "external_delivery": "DISABLED",
        "communication": "DISABLED",
    }
    fields["manifest_digest"] = compute_manifest_digest(fields)
    return DeliverablePackage(**fields)


def sign_off_package(
    package: DeliverablePackage,
    *,
    reviewer_id: str,
    status: Literal["SIGNED_OFF", "REJECTED"],
    notes: str | None = None,
    now: float | None = None,
) -> DeliverablePackage:
    """Record operator review sign-off or rejection on a deliverable package.

    Args:
        package: The current package.
        reviewer_id: Operator actor ID recording the review.
        status: Sign-off verdict (``SIGNED_OFF`` or ``REJECTED``).
        notes: Optional operator review notes.
        now: Optional review timestamp; defaults to current time.

    Returns:
        The updated, sealed ``DeliverablePackage``.

    Raises:
        ValueError: The package was already signed off or rejected.
    """
    if package.review_status != "AWAITING_HUMAN_SIGNOFF":
        raise ValueError("deliverable_already_reviewed")
    review_time = time.time() if now is None else now
    data = package.model_dump()
    data["review_status"] = status
    data["reviewed_by"] = reviewer_id
    data["reviewed_at"] = review_time
    data["review_notes"] = notes
    data["manifest_digest"] = compute_manifest_digest(data)
    return DeliverablePackage(**data)


def verify_package(package_data: dict[str, Any]) -> dict[str, Any]:
    """Verify cryptographic integrity and delivery constraints of a package.

    Args:
        package_data: Deliverable package mapping.

    Returns:
        Verification result mapping including boolean flags for report hash,
        manifest hash, disabled external communication, and overall validity.
    """
    report_text = package_data.get("report_markdown", "")
    expected_report_hash = (
        hashlib.sha256(report_text.encode("utf-8")).hexdigest()
        if isinstance(report_text, str)
        else ""
    )
    actual_report_hash = package_data.get("report_sha256", "")
    report_hash_valid = bool(expected_report_hash and expected_report_hash == actual_report_hash)

    expected_manifest_digest = compute_manifest_digest(package_data)
    actual_manifest_digest = package_data.get("manifest_digest", "")
    manifest_digest_valid = bool(
        expected_manifest_digest and expected_manifest_digest == actual_manifest_digest
    )

    external_disabled = package_data.get("external_delivery") == "DISABLED"
    communication_disabled = package_data.get("communication") == "DISABLED"

    valid = (
        report_hash_valid
        and manifest_digest_valid
        and external_disabled
        and communication_disabled
    )

    return {
        "valid": valid,
        "report_hash_valid": report_hash_valid,
        "manifest_digest_valid": manifest_digest_valid,
        "external_delivery_disabled": external_disabled,
        "communication_disabled": communication_disabled,
        "review_status": package_data.get("review_status"),
        "manifest_digest": actual_manifest_digest,
    }
