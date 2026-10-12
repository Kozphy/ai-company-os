"""Offline qualification of caller-supplied prospects and local proposal drafts."""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


class ProspectInput(BaseModel):
    """Caller-supplied prospect used for offline qualification.

    Attributes:
        domain: Lowercased hostname. It must match a dotted domain pattern.
        criteria: At most 20 named boolean checks. Names are nonblank and at
            most 128 characters.
        qualification_threshold: Score from 0 to 1 required to qualify.
            Defaults to 0.7.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    domain: str = Field(min_length=3, max_length=253)
    criteria: dict[str, bool] = Field(default_factory=dict)
    qualification_threshold: float = Field(default=0.7, ge=0, le=1)

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_domain(cls, value: Any) -> Any:
        """Lowercase and trim a domain string before validation.

        Args:
            value: Raw domain field.

        Returns:
            The stripped lowercase string, or the original value when it is
            not a string.
        """
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        """Require a dotted domain name.

        Args:
            value: Normalized domain.

        Returns:
            The accepted domain.

        Raises:
            ValueError: The value is not a domain of the expected shape.
        """
        if DOMAIN.fullmatch(value) is None:
            raise ValueError("valid prospect domain required")
        return value

    @model_validator(mode="after")
    def validate_criteria(self) -> "ProspectInput":
        """Require at most 20 bounded, nonblank criterion names.

        Returns:
            This prospect.

        Raises:
            ValueError: There are more than 20 criteria, or a name is blank,
                padded, or longer than 128 characters.
        """
        if len(self.criteria) > 20 or any(
            not key or key != key.strip() or len(key) > 128 for key in self.criteria
        ):
            raise ValueError("qualification requires at most 20 bounded, nonblank criterion names")
        return self


def qualify(prospect: ProspectInput) -> dict[str, Any]:
    """Score caller-supplied criteria and draft a proposal only when qualified.

    The score is the fraction of true criteria. An empty criteria map scores
    0 and stays unqualified. Qualified prospects receive a local markdown
    draft. Nothing is sent.

    Args:
        prospect: Validated prospect input.

    Returns:
        Stage, qualification details, proposal status, optional markdown, and
        ``outreach`` set to ``DISABLED``.
    """
    matched = sum(prospect.criteria.values())
    score = matched / len(prospect.criteria) if prospect.criteria else 0.0
    stage = (
        "QUALIFIED"
        if prospect.criteria and score >= prospect.qualification_threshold
        else "UNQUALIFIED"
    )
    draft = None
    if stage == "QUALIFIED":
        draft = (
            f"# Proposal draft for {prospect.domain}\n\n"
            "Offer: a read-only CI history audit using a customer-supplied export.\n\n"
            "Scope, repository, review window, price and acceptance terms require human agreement. "
            "Customer authorization must be recorded before processing a real audit export.\n\n"
            "Deliverable: an evidence-linked report for human review. "
            "No code changes, CI changes or external delivery are included.\n\n"
            "Qualification uses unverified caller-supplied criteria. "
            "This draft has not been sent or accepted.\n"
        )
    return {
        "domain": prospect.domain,
        "stage": stage,
        "qualification": {
            "criteria": prospect.criteria,
            "matched": matched,
            "score": score,
            "threshold": prospect.qualification_threshold,
            "input_status": "CALLER_SUPPLIED_UNVERIFIED",
        },
        "proposal_status": "DRAFT_ONLY" if draft else "WITHHELD_UNQUALIFIED",
        "proposal_markdown": draft,
        "outreach": "DISABLED",
    }
