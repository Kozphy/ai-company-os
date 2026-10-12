"""Local worker and deterministic evaluation gate."""

import time
import uuid

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from company_os import agents
from company_os.jobs import claim, fail, finish, start_evaluation
from company_os.schema import evaluations, evidence


def deterministic_evaluation(kind: str, payload: dict, output: dict) -> dict:
    review_marked = (
        any("human" in str(item).lower() for item in output.get("limitations", []))
        or output.get("review_status") == "AWAITING_HUMAN_SIGNOFF"
        or output.get("proposal_status") == "DRAFT_ONLY"
        or output.get("limitation") is not None
    )
    checks = {
        "workflow_matches": output.get("workflow") == kind,
        "offline_mode_is_explicit": output.get("mode") in {"OFFLINE_DEMO", "IMPORTED_OFFLINE_EXPORT"},
        "human_review_is_explicit": review_marked,
    }
    if kind == "engineering":
        checks["has_reproducible_input_window"] = isinstance(output.get("analysis"), dict)
    if kind == "research":
        checks["unverified_claims_not_presented_as_verified"] = all(
            x.get("reliability") == "UNVERIFIED" for x in output.get("sources", [])
        )
    if kind == "sales":
        checks["outbound_is_disabled"] = output.get("outbound_status") == "DISABLED"
    if kind == "delivery":
        checks["evidence_reference_is_linked"] = (
            bool(output.get("evidence_reference"))
            and output.get("input_evidence_status") in {"STORED_TENANT_EVIDENCE", "DEMO_ONLY"}
        )
    if kind == "finance":
        checks["unverified_financial_claims_not_counted"] = (
            output.get("bank_verified_income_micro_usd") is None
            and output.get("bank_verified_expenses_micro_usd") is None
            and output.get("gross_margin_micro_usd") is None
        )
    return {
        "version": "deterministic-v1",
        "passed": all(checks.values()),
        "checks": checks,
        "llm_judge": "NOT_RUN",
        "limitations": ["offline deterministic validation"],
    }


class Worker:
    def __init__(self, engine: Engine, *, lease_seconds: int = 60):
        self.engine = engine
        self.lease_seconds = lease_seconds
        self.owner = "worker-" + uuid.uuid4().hex

    def run_once(self, *, now: float | None = None) -> bool:
        moment = time.time() if now is None else now
        task = claim(self.engine, self.owner, self.lease_seconds, now=moment)
        if task is None:
            return False
        try:
            output = agents.execute(task["job_type"], task["payload"])
            if task["job_type"] == "delivery":
                reference = task["payload"].get("evidence_reference")
                if isinstance(reference, str) and reference.startswith("demo-"):
                    output["input_evidence_status"] = "DEMO_ONLY"
                else:
                    with self.engine.connect() as conn:
                        stored = conn.execute(
                            sa.select(evidence.c.id).where(
                                evidence.c.id == reference,
                                evidence.c.tenant_id == task["tenant_id"],
                            )
                        ).first()
                    if stored is None:
                        raise ValueError("delivery_evidence_not_found_for_tenant")
                    output["input_evidence_status"] = "STORED_TENANT_EVIDENCE"
            if not start_evaluation(self.engine, task, now=moment):
                return False
            report_reference = output.get("evidence_reference")
            evaluation = deterministic_evaluation(task["job_type"], task["payload"], output)
            if not evaluation["passed"]:
                raise ValueError("deterministic_evaluation_failed")
            if report_reference:
                output["delivery_input_evidence_reference"] = report_reference
            output["evaluation"] = evaluation
            from company_os.db import transaction

            with transaction(self.engine) as conn:
                conn.execute(
                    evaluations.insert().values(
                        id=str(uuid.uuid4()),
                        tenant_id=task["tenant_id"],
                        job_id=task["job_id"],
                        version=evaluation["version"],
                        body=evaluation,
                        created_at=moment,
                    )
                )
            if not finish(self.engine, task, output, now=moment):
                return False
        except Exception as exc:
            fail(self.engine, task, type(exc).__name__.lower(), now=moment)
        return True

    def run_forever(self, poll_seconds: float = 1.0) -> None:
        while True:
            if not self.run_once():
                time.sleep(poll_seconds)
