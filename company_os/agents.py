"""Five offline typed workflows. Inputs are data, never authority or executable code."""

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}$")
RUN_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100})/actions/runs/(\d+)$")
DOMAIN = re.compile(r"^(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,63}$")
PROMPT_INJECTION = re.compile(
    r"(?:"
    + "|".join(
        (
            r"ignore (?:all )?(?:previous|prior) instructions",
            r"reveal (?:the )?(?:secret|system prompt)",
            r"execute (?:this|the) command",
        )
    )
    + r")",
    re.IGNORECASE,
)
AGENTS = ("engineering", "research", "sales", "delivery", "finance")


def _safe(text: object, limit: int = 1000) -> str:
    value = "" if text is None else str(text)
    value = re.sub(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})", "[REDACTED]", value)
    return value[:limit]


def execute(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Produce an offline demonstration record and deterministic checks."""
    if kind == "engineering":
        return _engineering(payload)
    if kind == "research":
        sources = payload.get("sources", [])
        if not isinstance(sources, list) or len(sources) > 100:
            raise ValueError("invalid source collection")
        records = []
        seen: set[str] = set()
        for item in sources:
            if not isinstance(item, dict):
                continue
            url, title, published = (
                _safe(item.get("url"), 2000),
                _safe(item.get("title"), 500),
                item.get("published_at"),
            )
            ident = hashlib.sha256(url.encode()).hexdigest()
            if not url.startswith("https://") or ident in seen:
                continue
            seen.add(ident)
            records.append(
                {
                    "url": url,
                    "title": title,
                    "published_at": published,
                    "claim": _safe(item.get("claim")),
                    "reliability": "UNVERIFIED",
                    "content_is_untrusted": True,
                    "prompt_injection_signal": bool(
                        PROMPT_INJECTION.search(_safe(item.get("content"), 5000))
                    ),
                }
            )
        return {
            "workflow": "research",
            "mode": "OFFLINE_DEMO",
            "sources": records,
            "limitations": ["no retrieval performed", "claims and dates require human verification"],
        }
    if kind == "sales":
        record = payload.get("prospect", {})
        if not isinstance(record, dict):
            raise ValueError("invalid prospect")
        domain = _safe(record.get("domain", ""), 256).lower()
        if not DOMAIN.fullmatch(domain):
            raise ValueError("a domain is required; contact discovery and outreach are disabled")
        criteria = payload.get("criteria", {})
        if not isinstance(criteria, dict) or len(criteria) > 20:
            raise ValueError("invalid qualification criteria")
        fit = sum(1 for value in criteria.values() if value is True)
        return {
            "workflow": "sales",
            "mode": "OFFLINE_DEMO",
            "domain": domain,
            "qualification": {
                "criteria": criteria,
                "matched": fit,
                "score": round(fit / max(1, len(criteria)), 2),
            },
            "proposal_status": "DRAFT_ONLY",
            "outbound_status": "DISABLED",
        }
    if kind == "delivery":
        report = payload.get("report")
        evidence_id = _safe(payload.get("evidence_reference", ""), 64)
        if not isinstance(report, str) or not report or len(report) > 1_000_000 or not evidence_id:
            raise ValueError("validated evidence and bounded report required")
        return {
            "workflow": "delivery",
            "mode": "OFFLINE_DEMO",
            "evidence_reference": evidence_id,
            "report_sha256": hashlib.sha256(report.encode()).hexdigest(),
            "review_status": "AWAITING_HUMAN_SIGNOFF",
            "external_delivery": "DISABLED",
        }
    if kind == "finance":
        rows = payload.get("entries", [])
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError("invalid ledger entries")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid ledger row")
            kind_value, amount = row.get("kind"), row.get("amount_micro_usd")
            if kind_value not in {"income", "expense"} or not isinstance(amount, int) or amount < 0:
                raise ValueError("invalid ledger amount")
            # Caller-supplied flags and references are claims, not independent
            # financial evidence. No bank or accounting provider is integrated.
        return {
            "workflow": "finance",
            "mode": "OFFLINE_DEMO",
            "bank_verified_income_micro_usd": None,
            "bank_verified_expenses_micro_usd": None,
            "gross_margin_micro_usd": None,
            "entries_count": len(rows),
            "unverified_entries_count": len(rows),
            "pilot_price_hypothesis_usd": 149,
            "recorded_revenue_micro_usd": None,
            "limitation": (
                "no bank or accounting evidence adapter is configured; "
                "all submitted entries remain unverified"
            ),
        }
    raise ValueError("unsupported job type")


def _engineering(payload: dict[str, Any]) -> dict[str, Any]:
    export = payload.get("export")
    if payload.get("event") == "workflow_run":
        run_id = payload.get("run_id")
        if not isinstance(run_id, int):
            raise ValueError("invalid workflow run event")
        return {
            "workflow": "engineering",
            "mode": "IMPORTED_OFFLINE_EXPORT",
            "repository": _safe(payload.get("repository"), 256),
            "analysis": {
                "status": "INCOMPLETE",
                "run_id": run_id,
                "event_metadata": "RECEIVED",
                "logs": "UNAVAILABLE",
                "classification": "UNKNOWN",
                "findings": [],
            },
            "report_markdown": (
                "# CI failure event\n\nRun metadata received. Log retrieval is disabled; cause is UNKNOWN.\n"
            ),
            "adapter": "github-webhook-metadata-only",
            "limitations": ["GitHub event metadata only", "human review required"],
        }
    if not isinstance(export, dict) or export.get("schema") != "ci-audit.export.v1":
        raise ValueError("expected a ci-audit.export.v1 history export")
    if not REPOSITORY.fullmatch(str(export.get("repository", ""))) or export.get("private") is not True:
        raise ValueError("audit requires an explicitly authorized private repository marker")
    days = export.get("window_days")
    if not isinstance(days, int) or not 1 <= days <= 90:
        raise ValueError("audit window must be between 1 and 90 days")
    runs, jobs, failures = (export.get(key) for key in ("runs", "jobs", "failures"))
    if (
        not isinstance(runs, list)
        or not isinstance(jobs, list)
        or not isinstance(failures, list)
        or len(runs) > 5000
        or len(jobs) > 20000
    ):
        raise ValueError("invalid or oversized history export")
    safe = {**export, "runs": runs, "jobs": jobs, "failures": failures}
    for failure in safe["failures"]:
        if not isinstance(failure, dict):
            raise ValueError("invalid failure record")
        failure["message"] = _safe(failure.get("message", ""), 300)
        match = RUN_URL.fullmatch(str(failure.get("html_url", "")))
        failure["html_url"] = (
            str(failure["html_url"])
            if match and match.group(1) == export["repository"]
            else ""
        )
        failure["prompt_injection_signal"] = bool(PROMPT_INJECTION.search(failure["message"]))
    try:
        from ci_failure_orchestrator.ci_audit import analyze_export, render_report

        analysis = analyze_export(safe)
        _preserve_required_ci_gates(analysis)
        report = render_report(analysis)
        if analysis["policy_notice"] not in report:
            report = report.rstrip() + "\n\n## Policy note\n\n" + analysis["policy_notice"] + "\n"
        adapter = "ci-failure-orchestrator@f7b6cf2"
    except ImportError:
        analysis, report = _fallback_analysis(safe), None
        adapter = "kozphy-offline-analysis-v1"
    return {
        "workflow": "engineering",
        "mode": "IMPORTED_OFFLINE_EXPORT",
        "repository": export["repository"],
        "analysis": analysis,
        "report_markdown": report,
        "adapter": adapter,
        "limitations": [
            "export was supplied by caller and was not fetched from GitHub",
            "runner-minute estimates are not invoices",
            "human review required",
        ],
    }


def _preserve_required_ci_gates(analysis: dict[str, Any]) -> None:
    """Replace upstream advice that weakens mandatory CI checks."""
    prohibited = re.compile(
        r"quarantin|non[- ]blocking|delete (?:the )?tests?|skip (?:tests|checks|work)|"
        r"disable (?:the )?(?:tests?|checks?)|remove (?:the )?(?:tests?|checks?)",
        re.I,
    )
    for finding in analysis.get("findings", []):
        recommendation = str(finding.get("recommendation", ""))
        if prohibited.search(recommendation):
            finding["recommendation"] = (
                "Keep all required CI checks blocking. Reproduce and fix the underlying failure, "
                "preserve coverage, and obtain human review before changing the workflow."
            )
            finding["policy_review"] = "MANDATORY_GATES_PRESERVED"
    analysis["policy_notice"] = (
        "Recommendations are advisory. Required checks must not be weakened to obtain green CI."
    )


def _fallback_analysis(export: dict[str, Any]) -> dict[str, Any]:
    runs = [r for r in export["runs"] if isinstance(r, dict) and r.get("status") == "completed"]
    failed = sum(r.get("conclusion") in {"failure", "timed_out", "startup_failure"} for r in runs)
    success = sum(r.get("conclusion") == "success" for r in runs)
    failures = export["failures"]
    by_category: dict[str, int] = {}
    for failure in failures:
        category = _safe(failure.get("category", "unknown"), 64)
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "schema": "kozphy.ci-analysis.v1",
        "repository": export["repository"],
        "window_days": export["window_days"],
        "completed_runs": len(runs),
        "failed_runs": failed,
        "succeeded_runs": success,
        "failure_rate": failed / max(1, failed + success),
        "failure_categories": by_category,
        "findings": [],
        "generated_at": datetime.now(UTC).isoformat(),
    }
