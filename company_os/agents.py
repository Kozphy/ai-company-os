"""Five offline typed workflows. Inputs are data, never authority or executable code."""

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from company_os.sales import ProspectInput, qualify

REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}$")
RUN_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100})/actions/runs/(\d+)$")
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
    """Truncate text and replace common credential shapes.

    Args:
        text: Value to coerce to text. ``None`` becomes an empty string.
        limit: Maximum number of characters to keep.

    Returns:
        The redacted, truncated string.
    """
    value = "" if text is None else str(text)
    value = re.sub(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})", "[REDACTED]", value)
    return value[:limit]


def execute(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one offline workflow and return its demonstration record.

    Inputs are data. The result names its mode and the checks a human still
    has to perform. No workflow calls an external service.

    Args:
        kind: One of ``engineering``, ``research``, ``sales``, ``delivery``,
            or ``finance``.
        payload: Caller-supplied workflow input.

    Returns:
        A workflow record with an explicit offline mode and limitations.

    Raises:
        ValueError: ``kind`` is unsupported or ``payload`` fails that
            workflow's shape checks.
    """
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
            canonical_url = _canonical_source_url(url)
            if canonical_url is None:
                continue
            ident = hashlib.sha256(canonical_url.encode()).hexdigest()
            if ident in seen:
                continue
            seen.add(ident)
            publication_date, publication_status = _publication_date(published)
            records.append(
                {
                    "url": canonical_url,
                    "title": title,
                    "published_at": publication_date,
                    "publication_date_status": publication_status,
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
        prospect = ProspectInput.model_validate({
            "domain": record.get("domain"),
            "criteria": payload.get("criteria", {}),
            "qualification_threshold": payload.get("qualification_threshold", 0.7),
        })
        return {
            "workflow": "sales",
            "mode": "OFFLINE_DEMO",
            **qualify(prospect),
            "outbound_status": "DISABLED",
            "limitations": ["caller-supplied criteria are unverified; human review required"],
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


def _canonical_source_url(value: str) -> str | None:
    """Normalize an HTTPS source URL, or reject one that is not usable.

    Args:
        value: Candidate URL.

    Returns:
        A lowercase-host HTTPS URL without userinfo or a fragment, or
        ``None`` when the value is not a public HTTPS URL.
    """
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme.lower() != "https"
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or hostname.lower() == "localhost"
    ):
        return None
    netloc = hostname.lower() + (f":{port}" if port is not None else "")
    return urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))


def _publication_date(value: object) -> tuple[str | None, str]:
    """Classify a caller-supplied publication date without treating it as verified.

    Args:
        value: Raw date from a source record.

    Returns:
        The parsed ISO timestamp, or ``None``, and a status of ``UNKNOWN``,
        ``INVALID``, or ``PARSED_UNVERIFIED``.
    """
    if value is None or value == "":
        return None, "UNKNOWN"
    if not isinstance(value, str):
        return None, "INVALID"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, "INVALID"
    return parsed.isoformat(), "PARSED_UNVERIFIED"


def _engineering(payload: dict[str, Any]) -> dict[str, Any]:
    """Build an engineering record from webhook metadata or a CI history export.

    A ``workflow_run`` payload records metadata only. A history export must
    declare a private repository and a window of 1 to 90 days. When the pinned
    CI adapter is installed, its advice is rewritten so required checks stay
    blocking. Otherwise a local count of completed runs is returned.

    Args:
        payload: Engineering job payload.

    Returns:
        An imported offline engineering record. The markdown report is
        ``None`` when the external adapter is not installed.

    Raises:
        ValueError: The event or export is invalid, oversized, or not marked
            as an authorized private repository.
    """
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
    """Replace upstream advice that weakens mandatory CI checks.

    Args:
        analysis: Mutable analysis mapping from the CI adapter. Findings whose
            recommendations drop, skip, quarantine, or make checks
            non-blocking are rewritten in place. A policy notice is always set.
    """
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
    """Summarize a CI history export without the external adapter.

    Args:
        export: A ``ci-audit.export.v1`` mapping that already passed shape checks.

    Returns:
        Counts of completed, failed, and succeeded runs, a failure rate, and
        redacted failure categories. Findings are empty.
    """
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
