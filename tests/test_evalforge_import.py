import json

import pytest

from company_os.evalforge_import import EVALFORGE_REVISION, EvalForgeImportError, summarize_export


def sample_export():
    return json.dumps(
        {
            "run_id": 7,
            "project_id": "audit-demo",
            "status": "completed",
            "results": [
                {"result_id": 1, "correct": False, "needs_human_review": True, "release_allowed": False}
            ],
        }
    )


def test_evalforge_import_is_unverified_and_supplementary():
    result = summarize_export(sample_export(), EVALFORGE_REVISION)
    assert result["state"] == "UNVERIFIED_IMPORTED"
    assert result["decision"] == "REVIEW_ONLY"
    assert result["reported_failed_results"] == 1
    assert result["reported_human_review_results"] == 1
    assert result["source_revision_verified"] is False
    assert "raw prompts" in result["limitations"][-1]


def test_evalforge_import_rejects_unpinned_or_malformed_artifacts():
    with pytest.raises(EvalForgeImportError):
        summarize_export(sample_export(), "0" * 40)
    with pytest.raises(EvalForgeImportError):
        summarize_export("[]", EVALFORGE_REVISION)


def test_api_import_is_tenant_scoped_idempotent_and_does_not_change_job(client, auth):
    created = client.post(
        "/v1/jobs", headers=auth,
        json={"job_type": "finance", "idempotency_key": "eval-import-target", "payload": {}},
    )
    job_id = created.json()["job_id"]
    body = {"source_revision": EVALFORGE_REVISION, "artifact_json": sample_export()}
    url = f"/v1/jobs/{job_id}/evaluations/evalforge"
    first = client.post(url, headers=auth, json=body)
    second = client.post(url, headers=auth, json=body)
    assert first.status_code == 201
    assert first.json()["evaluation_id"] == second.json()["evaluation_id"]
    assert first.json()["evaluation"]["decision"] == "REVIEW_ONLY"
    assert client.get(f"/v1/jobs/{job_id}", headers=auth).json()["status"] == "QUEUED"
    assert client.post(url, headers={"Authorization": "Bearer member-a"}, json=body).status_code == 403
    assert client.post(
        url, headers={"Authorization": "Bearer operator-b"}, json=body
    ).status_code == 404
    assert client.post(
        url, headers=auth, json={**body, "source_revision": "0" * 40}
    ).status_code == 422
