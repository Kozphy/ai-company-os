import pytest
from fastapi.testclient import TestClient

from company_os.agents import execute
from company_os.api import create_app
from company_os.db import transaction
from company_os.schema import prospects
from company_os.worker import deterministic_evaluation


def test_prospect_qualification_draft_replay_and_persistence(client, auth, settings):
    payload = {
        "domain": " EXAMPLE.test ",
        "criteria": {"uses_ci": True, "needs_audit": True, "has_budget": False},
        "qualification_threshold": 0.6,
    }
    response = client.post("/v1/prospects", headers=auth, json=payload)
    assert response.status_code == 201
    stored = response.json()
    assert stored["stage"] == "QUALIFIED"
    assert stored["domain"] == "example.test"
    assert stored["qualification"]["score"] == pytest.approx(2 / 3)
    assert stored["qualification"]["input_status"] == "CALLER_SUPPLIED_UNVERIFIED"
    assert stored["proposal_status"] == "DRAFT_ONLY"
    assert "example.test" in stored["proposal_markdown"]
    assert "authorization" in stored["proposal_markdown"]
    assert stored["outreach"] == "DISABLED"
    output = execute("sales", {
        "prospect": {"domain": payload["domain"]},
        "criteria": payload["criteria"],
        "qualification_threshold": payload["qualification_threshold"],
    })
    assert output["qualification"] == stored["qualification"]
    assert output["proposal_markdown"] == stored["proposal_markdown"]
    assert deterministic_evaluation("sales", {}, output)["passed"]
    output["qualification"]["input_status"] = "VERIFIED"
    assert not deterministic_evaluation("sales", {}, output)["passed"]
    replay = client.post("/v1/prospects", headers=auth, json=payload).json()
    assert replay == {**stored, "created": False}
    changed = {**payload, "criteria": {"uses_ci": False}}
    assert client.post("/v1/prospects", headers=auth, json=changed).status_code == 409
    with TestClient(create_app(settings)) as reopened:
        listed = reopened.get("/v1/prospects", headers=auth).json()
        assert listed == [{key: value for key, value in stored.items() if key != "created"}]
        assert reopened.get("/v1/dashboard", headers=auth).json()["sales_pipeline"] == {"QUALIFIED": 1}
    reopened.app.state.engine.dispose()


def test_prospects_are_tenant_scoped_and_reader_cannot_write(client, auth):
    body = {"domain": "example.test", "criteria": {"fit": True}}
    assert client.get("/v1/prospects").status_code == 401
    assert client.post("/v1/prospects", json=body).status_code == 401
    reader = {"Authorization": "Bearer reader-a"}
    assert client.post("/v1/prospects", headers=reader, json=body).status_code == 403
    first = client.post("/v1/prospects", headers=auth, json=body).json()
    tenant_b = {"Authorization": "Bearer operator-b"}
    assert client.get("/v1/prospects", headers=tenant_b).json() == []
    second = client.post("/v1/prospects", headers=tenant_b, json=body).json()
    assert first["prospect_id"] != second["prospect_id"]
    assert [row["prospect_id"] for row in client.get("/v1/prospects", headers=reader).json()] == [
        first["prospect_id"]
    ]


@pytest.mark.parametrize("body", [
    {"domain": "-invalid.test"},
    {"domain": "invalid-.test"},
    {"domain": "a" * 64 + ".test"},
    {"domain": "https://example.test"},
    {"domain": "example.test", "criteria": {"fit": "true"}},
    {"domain": "example.test", "criteria": {"fit": 1}},
    {"domain": "example.test", "criteria": {" ": True}},
    {"domain": "example.test", "criteria": {"x" * 129: True}},
    {"domain": "example.test", "criteria": {str(n): True for n in range(21)}},
    {"domain": "example.test", "qualification_threshold": 1.1},
    {"domain": "example.test", "qualification_threshold": True},
    {"domain": "example.test", "qualified": True},
])
def test_invalid_qualification_does_not_create_prospect(client, auth, body):
    assert client.post("/v1/prospects", headers=auth, json=body).status_code == 422
    assert client.get("/v1/prospects", headers=auth).json() == []


@pytest.mark.parametrize("criteria,threshold", [
    ({"a": True, "b": True, "c": False}, 0.67),
    ({}, 0),
])
def test_unqualified_proposals_withheld_in_api_and_worker(client, auth, criteria, threshold):
    payload = {"domain": "example.test", "criteria": criteria, "qualification_threshold": threshold}
    stored = client.post("/v1/prospects", headers=auth, json=payload).json()
    job_payload = {
        "prospect": {"domain": payload["domain"]},
        "criteria": criteria,
        "qualification_threshold": threshold,
    }
    output = execute("sales", job_payload)
    for result in (stored, output):
        assert result["stage"] == "UNQUALIFIED"
        assert result["proposal_status"] == "WITHHELD_UNQUALIFIED"
        assert result["proposal_markdown"] is None
    assert stored["qualification"] == output["qualification"]
    assert deterministic_evaluation("sales", job_payload, output)["passed"]
    output["proposal_markdown"] = "Send this proposal"
    assert not deterministic_evaluation("sales", job_payload, output)["passed"]
    submitted = client.post("/v1/jobs", headers=auth, json={
        "job_type": "sales", "idempotency_key": "unqualified", "payload": job_payload,
    }).json()
    client.post("/v1/worker/run-once", headers=auth)
    assert client.get(f"/v1/jobs/{submitted['job_id']}", headers=auth).json()["status"] == "COMPLETED"


def test_sales_worker_rejects_coerced_criteria():
    with pytest.raises(ValueError):
        execute("sales", {"prospect": {"domain": "example.test"}, "criteria": {"fit": "true"}})


def test_legacy_prospect_replay_preserves_existing_record(client, auth):
    legacy = {"domain": "example.test", "qualification": {}, "outreach": "DISABLED"}
    with transaction(client.app.state.engine) as conn:
        conn.execute(prospects.insert().values(
            id="legacy", tenant_id="a", domain="example.test", stage="UNQUALIFIED", body=legacy,
        ))
    result = client.post("/v1/prospects", headers=auth, json={"domain": "example.test"}).json()
    assert result == {**legacy, "prospect_id": "legacy", "created": False, "stage": "UNQUALIFIED"}
    assert len(client.get("/v1/prospects", headers=auth).json()) == 1
