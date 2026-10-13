from fastapi.testclient import TestClient

from company_os.api import create_app
from company_os.delivery import build_package, verify_package
from company_os.worker import deterministic_evaluation


def test_delivery_package_creation_and_retrieval(client, auth):
    # Queue a demo delivery job
    delivery_job = client.post(
        "/v1/jobs",
        headers=auth,
        json={
            "job_type": "delivery",
            "idempotency_key": "delivery-demo-1",
            "payload": {
                "report": "# Executive Audit Summary\n\nAll CI checks passed deterministically.",
                "evidence_reference": "demo-evidence-1",
                "title": "Quarterly CI Audit",
            },
        },
    ).json()

    # Process job with worker
    client.post("/v1/worker/run-once", headers=auth)
    job_id = delivery_job["job_id"]
    job_view = client.get(f"/v1/jobs/{job_id}", headers=auth).json()
    assert job_view["status"] == "COMPLETED"

    # Retrieve deliverable package
    pkg = client.get(f"/v1/jobs/{job_id}/deliverable", headers=auth).json()
    assert pkg["job_id"] == job_id
    assert pkg["tenant_id"] == "a"
    assert pkg["report_title"] == "Quarterly CI Audit"
    assert "Executive Audit Summary" in pkg["report_markdown"]
    assert pkg["review_status"] == "AWAITING_HUMAN_SIGNOFF"
    assert pkg["external_delivery"] == "DISABLED"
    assert pkg["communication"] == "DISABLED"
    assert len(pkg["report_sha256"]) == 64
    assert len(pkg["manifest_digest"]) == 64

    # Verify integrity
    verified = client.get(f"/v1/jobs/{job_id}/deliverable/verify", headers=auth).json()
    assert verified["valid"] is True
    assert verified["report_hash_valid"] is True
    assert verified["manifest_digest_valid"] is True
    assert verified["external_delivery_disabled"] is True
    assert verified["communication_disabled"] is True
    assert verified["review_status"] == "AWAITING_HUMAN_SIGNOFF"


def test_deliverable_signoff_immutability_and_audit(client, auth):
    # Queue and process delivery job
    job = client.post(
        "/v1/jobs",
        headers=auth,
        json={
            "job_type": "delivery",
            "idempotency_key": "delivery-signoff-1",
            "payload": {
                "report": "Final Report content",
                "evidence_reference": "demo-signoff-ref",
            },
        },
    ).json()
    client.post("/v1/worker/run-once", headers=auth)
    job_id = job["job_id"]

    # Sign off by operator
    signoff_payload = {"status": "SIGNED_OFF", "notes": "Approved for local archiving"}
    signed = client.post(
        f"/v1/jobs/{job_id}/deliverable/signoff", headers=auth, json=signoff_payload
    ).json()
    assert signed["review_status"] == "SIGNED_OFF"
    assert signed["reviewed_by"] == "alice"
    assert signed["reviewed_at"] is not None
    assert signed["review_notes"] == "Approved for local archiving"

    # Idempotent replay with same status and notes succeeds
    replay = client.post(
        f"/v1/jobs/{job_id}/deliverable/signoff", headers=auth, json=signoff_payload
    ).json()
    assert replay["manifest_digest"] == signed["manifest_digest"]
    assert replay["review_status"] == "SIGNED_OFF"

    # Conflicting change to an already signed-off deliverable returns 409
    conflicting = {"status": "REJECTED", "notes": "Changed my mind"}
    conflict_resp = client.post(
        f"/v1/jobs/{job_id}/deliverable/signoff", headers=auth, json=conflicting
    )
    assert conflict_resp.status_code == 409
    assert "immutable" in conflict_resp.json()["detail"]

    # Verify endpoint reflects SIGNED_OFF and remains valid
    verified = client.get(f"/v1/jobs/{job_id}/deliverable/verify", headers=auth).json()
    assert verified["valid"] is True
    assert verified["review_status"] == "SIGNED_OFF"


def test_deliverable_tampering_detection():
    pkg = build_package(
        tenant_id="a",
        job_id="job-123",
        report_title="Original Title",
        report_markdown="# Clean Report",
        evidence_reference="ev-123",
        evidence_digest="d" * 64,
        evidence_status="STORED_TENANT_EVIDENCE",
    )
    pkg_data = pkg.model_dump()
    assert verify_package(pkg_data)["valid"] is True

    # Tamper with markdown text
    tampered_report = dict(pkg_data)
    tampered_report["report_markdown"] = "# Tampered Report Content"
    check = verify_package(tampered_report)
    assert check["valid"] is False
    assert check["report_hash_valid"] is False

    # Tamper with review metadata
    tampered_metadata = dict(pkg_data)
    tampered_metadata["reviewed_by"] = "malicious_actor"
    check2 = verify_package(tampered_metadata)
    assert check2["valid"] is False
    assert check2["manifest_digest_valid"] is False

    # Tamper with external delivery flag
    tampered_delivery = dict(pkg_data)
    tampered_delivery["external_delivery"] = "ENABLED"
    check3 = verify_package(tampered_delivery)
    assert check3["valid"] is False
    assert check3["external_delivery_disabled"] is False


def test_deliverable_packaging_from_completed_job(client, auth):
    # Queue and process engineering demo job
    eng_job = client.post(
        "/v1/jobs",
        headers=auth,
        json={
            "job_type": "engineering",
            "idempotency_key": "eng-pkg-demo",
            "payload": {"demo": True},
        },
    ).json()
    job_id = eng_job["job_id"]

    # Attempt packaging before job completion returns 409
    assert client.post(f"/v1/jobs/{job_id}/deliverable", headers=auth).status_code == 409

    # Run worker to complete engineering job
    client.post("/v1/worker/run-once", headers=auth)
    assert client.get(f"/v1/jobs/{job_id}", headers=auth).json()["status"] == "COMPLETED"

    # Package explicitly with custom report and title
    custom_pkg = client.post(
        f"/v1/jobs/{job_id}/deliverable",
        headers=auth,
        json={
            "report_title": "Custom Engineering Deliverable",
            "report_markdown": "## Validated Engineering Findings\n\nAll CI checks intact.",
            "evidence_reference": "ev-ref-eng",
        },
    ).json()
    assert custom_pkg["report_title"] == "Custom Engineering Deliverable"
    assert custom_pkg["review_status"] == "AWAITING_HUMAN_SIGNOFF"

    # Non-existent job returns 404
    assert client.post("/v1/jobs/non-existent-job/deliverable", headers=auth).status_code == 404
    assert client.get("/v1/jobs/non-existent-job/deliverable", headers=auth).status_code == 404


def test_delivery_tenant_isolation_and_role_permissions(client, auth):
    # Setup delivery in Tenant A
    delivery_a = client.post(
        "/v1/jobs",
        headers=auth,
        json={
            "job_type": "delivery",
            "idempotency_key": "delivery-tenant-isolation",
            "payload": {"report": "Tenant A Secret Report", "evidence_reference": "demo-ev-a"},
        },
    ).json()
    client.post("/v1/worker/run-once", headers=auth)
    job_id = delivery_a["job_id"]

    # Anonymous denied
    assert client.get(f"/v1/jobs/{job_id}/deliverable").status_code == 401
    assert (
        client.post(
            f"/v1/jobs/{job_id}/deliverable/signoff", json={"status": "SIGNED_OFF"}
        ).status_code
        == 401
    )

    # Reader cannot sign off
    reader = {"Authorization": "Bearer reader-a"}
    assert client.post(
        f"/v1/jobs/{job_id}/deliverable/signoff", headers=reader, json={"status": "SIGNED_OFF"}
    ).status_code == 403
    # Reader can view and verify
    assert client.get(f"/v1/jobs/{job_id}/deliverable", headers=reader).status_code == 200
    assert client.get(f"/v1/jobs/{job_id}/deliverable/verify", headers=reader).status_code == 200

    # Tenant B cannot view, verify or sign off
    tenant_b = {"Authorization": "Bearer operator-b"}
    assert client.get(f"/v1/jobs/{job_id}/deliverable", headers=tenant_b).status_code == 404
    assert client.get(f"/v1/jobs/{job_id}/deliverable/verify", headers=tenant_b).status_code == 404
    assert client.post(
        f"/v1/jobs/{job_id}/deliverable/signoff", headers=tenant_b, json={"status": "SIGNED_OFF"}
    ).status_code == 404


def test_deterministic_evaluation_delivery_gate():
    base_output = {
        "workflow": "delivery",
        "evidence_reference": "demo-ref",
        "input_evidence_status": "DEMO_ONLY",
        "review_status": "AWAITING_HUMAN_SIGNOFF",
        "external_delivery": "DISABLED",
        "communication": "DISABLED",
        "report_sha256": "a" * 64,
    }
    assert deterministic_evaluation("delivery", {}, base_output)["passed"] is True

    # External delivery enabled fails gate
    bad_output_1 = dict(base_output, external_delivery="ENABLED")
    assert deterministic_evaluation("delivery", {}, bad_output_1)["passed"] is False

    # Communication enabled fails gate
    bad_output_2 = dict(base_output, communication="ENABLED")
    assert deterministic_evaluation("delivery", {}, bad_output_2)["passed"] is False

    # Invalid review status fails gate
    bad_output_3 = dict(base_output, review_status="AUTO_APPROVED")
    assert deterministic_evaluation("delivery", {}, bad_output_3)["passed"] is False

    # Missing report hash fails gate
    bad_output_4 = dict(base_output, report_sha256=None)
    assert deterministic_evaluation("delivery", {}, bad_output_4)["passed"] is False


def test_deliverable_persistence_across_app_restart(client, auth, settings):
    job = client.post(
        "/v1/jobs",
        headers=auth,
        json={
            "job_type": "delivery",
            "idempotency_key": "delivery-restart-test",
            "payload": {"report": "Persistent Report Content", "evidence_reference": "demo-restart-ref"},
        },
    ).json()
    client.post("/v1/worker/run-once", headers=auth)
    job_id = job["job_id"]

    client.post(
        f"/v1/jobs/{job_id}/deliverable/signoff",
        headers=auth,
        json={"status": "SIGNED_OFF", "notes": "Restart durability test"},
    )

    with TestClient(create_app(settings)) as reopened:
        pkg = reopened.get(f"/v1/jobs/{job_id}/deliverable", headers=auth).json()
        assert pkg["review_status"] == "SIGNED_OFF"
        assert pkg["review_notes"] == "Restart durability test"
        verified = reopened.get(f"/v1/jobs/{job_id}/deliverable/verify", headers=auth).json()
        assert verified["valid"] is True
        assert verified["review_status"] == "SIGNED_OFF"
    reopened.app.state.engine.dispose()
