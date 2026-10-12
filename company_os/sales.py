"""Offline qualification of caller-supplied prospects and local proposal drafts."""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


class ProspectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    domain: str = Field(min_length=3, max_length=253)
    criteria: dict[str, bool] = Field(default_factory=dict)
    qualification_threshold: float = Field(default=0.7, ge=0, le=1)

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_domain(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        if DOMAIN.fullmatch(value) is None:
            raise ValueError("valid prospect domain required")
        return value

    @model_validator(mode="after")
    def validate_criteria(self) -> "ProspectInput":
        if len(self.criteria) > 20 or any(
            not key or key != key.strip() or len(key) > 128 for key in self.criteria
        ):
            raise ValueError("qualification requires at most 20 bounded, nonblank criterion names")
        return self


def qualify(prospect: ProspectInput) -> dict[str, Any]:
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
