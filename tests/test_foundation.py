import asyncio

import pytest
from pydantic import ValidationError

from company_os.body_limit import BodyLimitMiddleware
from company_os.config import Settings


def test_health_schema_and_auth(client, auth):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").json() == {"ready": True}
    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers=auth).json()["tenant_id"] == "a"
    assert client.get("/v1/me", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_operator_dashboard_is_served_without_embedded_credentials(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Operator token" in response.text
    assert "localStorage" not in response.text


def test_oversized_job_payload_rejected_at_asgi_boundary(client, auth):
    response = client.post(
        "/v1/jobs",
        headers=auth,
        json={"job_type": "research", "idempotency_key": "large", "payload": {"content": "x" * 1_000_001}},
    )
    assert response.status_code == 413


def test_streamed_size_limit_without_content_length():
    async def scenario():
        async def downstream(scope, receive, send):
            await receive()

        async def receive():
            return {"type": "http.request", "body": b"x" * 9, "more_body": False}

        messages = []

        async def send(message):
            messages.append(message)

        middleware = BodyLimitMiddleware(downstream, max_bytes=8)
        await middleware({"type": "http", "headers": []}, receive, send)
        assert messages[0]["status"] == 413

    asyncio.run(scenario())


def test_production_and_identity_spoofing_fail_closed():
    with pytest.raises(ValidationError):
        Settings(environment="production")
    with pytest.raises(ValidationError):
        Settings(identities_json='{"token": {"tenant_id":"a","actor_id":"a","role":"operator"}}')
