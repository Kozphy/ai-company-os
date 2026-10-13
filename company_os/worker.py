"""Local worker and deterministic evaluation gate."""

import hashlib
import time
import uuid

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from company_os import agents
from company_os.authorization import validate_export, validate_scope
from company_os.delivery import build_package
from company_os.jobs import claim, fail, finish, start_evaluation
from company_os.schema import evaluations, evidence


def deterministic_evaluation(kind: str, payload: dict, output: dict) -> dict:
    """Check an offline workflow result against fixed local rules.

    ``payload`` is accepted so callers share one signature with the workflow
    runner and is not scored. Research sources must stay unverified. Sales
    proposals appear only for qualified prospects. Delivery must name stored
    tenant evidence plus a valid authorization, or a ``demo-`` reference.
    Finance must leave bank figures empty. No model judge is run.

    Args:
        kind: Workflow name the output claims to serve.
        payload: Job payload. It is not inspected.
        output: Workflow result to score.

    Returns:
        A ``deterministic-v1`` report with ``passed``, per-check booleans,
        and ``llm_judge`` set to ``NOT_RUN``.
    """
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
        checks["citation_dates_are_explicitly_qualified"] = all(
            x.get("publication_date_status") in {"UNKNOWN", "INVALID", "PARSED_UNVERIFIED"}
            for x in output.get("sources", [])
        )
    if kind == "sales":
        checks["outbound_is_disabled"] = output.get("outbound_status") == "DISABLED"
        checks["qualification_remains_unverified"] = (
            output.get("qualification", {}).get("input_status") == "CALLER_SUPPLIED_UNVERIFIED"
        )
        checks["proposal_requires_qualification"] = (
            output.get("stage") == "QUALIFIED"
            and output.get("proposal_status") == "DRAFT_ONLY"
            and isinstance(output.get("proposal_markdown"), str)
            and bool(output["proposal_markdown"])
        ) or (
            output.get("stage") == "UNQUALIFIED"
            and output.get("proposal_status") == "WITHHELD_UNQUALIFIED"
            and output.get("proposal_markdown") is None
        )
    if kind == "delivery":
        checks["evidence_reference_is_linked"] = (
            bool(output.get("evidence_reference"))
            and output.get("input_evidence_status") == "STORED_TENANT_EVIDENCE"
            and output.get("authorization_status") == "VALID"
        ) or (
            bool(output.get("evidence_reference"))
            and output.get("input_evidence_status") == "DEMO_ONLY"
        )
        checks["review_status_is_awaiting_signoff"] = (
            output.get("review_status") == "AWAITING_HUMAN_SIGNOFF"
        )
        checks["external_delivery_disabled"] = (
            output.get("external_delivery") == "DISABLED"
        )
        checks["communication_disabled"] = (
            output.get("communication") == "DISABLED"
        )
        checks["report_sha256_present"] = bool(output.get("report_sha256"))
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
    """Claim one job, run its offline workflow, and store the evaluation."""

    def __init__(self, engine: Engine, *, lease_seconds: int = 60):
        """Bind this worker to an engine and a fresh owner id.

        Args:
            engine: Database engine.
            lease_seconds: Lease length in seconds.
        """
        self.engine = engine
        self.lease_seconds = lease_seconds
        self.owner = "worker-" + uuid.uuid4().hex

    def run_once(self, *, now: float | None = None) -> bool:
        """Process at most one leased job.

        Engineering exports are checked against a customer authorization
        unless the payload is marked ``demo``. Delivery requires stored
        same-tenant evidence and a covering authorization, except references
        that start with ``demo-``. A failed deterministic check is a
        permanent failure. Other exceptions are retried by the queue.

        Args:
            now: Unix timestamp used for the claim, authorization, and
                completion. Defaults to the current time.

        Returns:
            ``True`` when a job was claimed, including when that job then
            failed. ``False`` when the queue had no work or the lease was
            lost before completion.
        """
        moment = time.time() if now is None else now
        task = claim(self.engine, self.owner, self.lease_seconds, now=moment)
        if task is None:
            return False
        try:
            export_authorization = None
            if (
                task["job_type"] == "engineering"
                and isinstance(task["payload"].get("export"), dict)
                and task["payload"].get("demo") is not True
            ):
                export_authorization = validate_export(
                    self.engine, task["tenant_id"], task["payload"], now=moment
                )
            output = agents.execute(task["job_type"], task["payload"])
            if export_authorization:
                output["customer_authorization_reference"] = export_authorization["authorization_id"]
                output["authorization_scope_digest"] = export_authorization["scope_digest"]
            if task["job_type"] == "delivery":
                reference = task["payload"].get("evidence_reference")
                stored = None
                if isinstance(reference, str) and reference.startswith("demo-"):
                    output["input_evidence_status"] = "DEMO_ONLY"
                    output["authorization_status"] = "DEMO_ONLY"
                else:
                    with self.engine.connect() as conn:
                        stored = conn.execute(
                            sa.select(evidence.c.id, evidence.c.body, evidence.c.digest).where(
                                evidence.c.id == reference,
                                evidence.c.tenant_id == task["tenant_id"],
                            )
                        ).first()
                    if stored is None:
                        raise ValueError("delivery_evidence_not_found_for_tenant")
                    output["input_evidence_status"] = "STORED_TENANT_EVIDENCE"
                    source = stored.body
                    analysis = source.get("analysis", {}) if isinstance(source, dict) else {}
                    validated_scope = validate_scope(
                        self.engine,
                        tenant_id=task["tenant_id"],
                        authorization_id=task["payload"].get("authorization_reference"),
                        repository=source.get("repository") if isinstance(source, dict) else None,
                        window_start=analysis.get("since"),
                        window_end=analysis.get("collected_at"),
                        now=moment,
                    )
                    output["authorization_status"] = "VALID"
                    output["customer_authorization_reference"] = validated_scope["authorization_id"]
                    output["authorization_scope_digest"] = validated_scope["scope_digest"]
                ref_str = str(reference or "")
                evidence_digest = (
                    stored.digest
                    if stored is not None
                    else f"demo-{hashlib.sha256(ref_str.encode()).hexdigest()[:16]}"
                )
                package = build_package(
                    tenant_id=task["tenant_id"],
                    job_id=task["job_id"],
                    report_title=output.get("title", "Delivery Report"),
                    report_markdown=task["payload"]["report"],
                    evidence_reference=ref_str,
                    evidence_digest=evidence_digest,
                    evidence_status=output["input_evidence_status"],
                    authorization_reference=output.get("customer_authorization_reference"),
                    authorization_scope_digest=output.get("authorization_scope_digest"),
                    authorization_status=output.get("authorization_status", "NONE"),
                    created_at=moment,
                )
                output["package"] = package.model_dump()
                output["manifest_digest"] = package.manifest_digest
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
        except ValueError as exc:
            fail(self.engine, task, type(exc).__name__.lower(), permanent=True, now=moment)
        except Exception as exc:
            fail(self.engine, task, type(exc).__name__.lower(), now=moment)
        return True

    def run_forever(self, poll_seconds: float = 1.0) -> None:
        """Poll ``run_once`` until the process is stopped.

        Args:
            poll_seconds: Sleep interval after a poll that finds no work.
        """
        while True:
            if not self.run_once():
                time.sleep(poll_seconds)
