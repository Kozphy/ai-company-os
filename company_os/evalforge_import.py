"""Strict, review-only parser for the audited EvalForge JSON export shape.

This module imports metadata only. EvalForge source is proprietary and remains
separate; imported artifacts never override the local deterministic gate.
"""

import hashlib
import json
from typing import Any

EVALFORGE_REVISION = "4fcec3bc4fa816a533d3445ebc3dc82d38871659"


class EvalForgeImportError(ValueError):
    pass


def summarize_export(artifact_json: str, source_revision: str) -> dict[str, Any]:
    if source_revision != EVALFORGE_REVISION:
        raise EvalForgeImportError("unsupported_evalforge_revision")
    try:
        artifact = json.loads(artifact_json)
    except (ValueError, TypeError) as exc:
        raise EvalForgeImportError("invalid_evalforge_json") from exc
    if not isinstance(artifact, dict):
        raise EvalForgeImportError("invalid_evalforge_export")
    run_id = artifact.get("run_id")
    project_id = artifact.get("project_id")
    rows = artifact.get("results")
    if (
        not isinstance(run_id, (str, int))
        or isinstance(run_id, bool)
        or not isinstance(project_id, (str, int))
        or isinstance(project_id, bool)
        or not isinstance(rows, list)
        or not rows
        or len(rows) > 10_000
    ):
        raise EvalForgeImportError("invalid_evalforge_export_shape")
    if any(not isinstance(row, dict) or not isinstance(row.get("result_id"), (str, int)) for row in rows):
        raise EvalForgeImportError("invalid_evalforge_result_shape")
    return {
        "source": "EvalForge",
        "source_revision": source_revision,
        "source_revision_verified": False,
        "artifact_sha256": hashlib.sha256(artifact_json.encode("utf-8")).hexdigest(),
        "run_id": str(run_id),
        "project_id": str(project_id),
        "result_count": len(rows),
        "reported_failed_results": sum(row.get("correct") is False for row in rows),
        "reported_human_review_results": sum(
            row.get("needs_human_review") is True for row in rows
        ),
        "state": "UNVERIFIED_IMPORTED",
        "decision": "REVIEW_ONLY",
        "limitations": [
            "source revision is caller-asserted, not cryptographically attested",
            "imported values are untrusted and cannot override local deterministic evaluation",
            "raw prompts, responses, and source payload are not persisted",
        ],
    }
