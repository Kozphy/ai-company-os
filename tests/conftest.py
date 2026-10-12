import hashlib
import json

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from company_os.api import create_app
from company_os.config import Settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "test.db").as_posix()
    monkeypatch.setenv("KOZPHY_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    entries = {
        "operator-a": {"tenant_id": "a", "actor_id": "alice", "role": "operator"},
        "member-a": {"tenant_id": "a", "actor_id": "mike", "role": "member"},
        "operator-b": {"tenant_id": "b", "actor_id": "bob", "role": "operator"},
        "reader-a": {"tenant_id": "a", "actor_id": "ray", "role": "reader"},
    }
    identities = {hashlib.sha256(k.encode()).hexdigest(): v for k, v in entries.items()}
    return Settings(environment="test", database_url=url, identities_json=json.dumps(identities))


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as value:
        yield value
    value.app.state.engine.dispose()


@pytest.fixture
def auth():
    return {"Authorization": "Bearer operator-a"}
