"""Operator commands for local-only setup and processes."""

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path
from typing import Any

import uvicorn
from alembic import command
from alembic.config import Config

from company_os.config import Settings
from company_os.scheduler import Scheduler
from company_os.worker import Worker


def _alembic() -> Config:
    config = Config("alembic.ini")
    return config


def setup(database_url: str, tenant: str, actor: str) -> None:
    env_path = Path(".env")
    if env_path.exists():
        raise SystemExit(".env already exists; remove it yourself to reinitialize")
    token = secrets.token_urlsafe(32)
    identity_hash = hashlib.sha256(token.encode()).hexdigest()
    identities = {
        identity_hash: {"tenant_id": tenant, "actor_id": actor, "role": "operator"}
    }
    password = secrets.token_urlsafe(36)
    values = [
        "KOZPHY_ENVIRONMENT=local",
        f"KOZPHY_DATABASE_URL={database_url}",
        "KOZPHY_IDENTITIES_JSON=" + json.dumps(identities, separators=(",", ":")),
        "KOZPHY_TENANT_BUDGET_MICRO_USD=1000000",
        "POSTGRES_PASSWORD=" + password,
    ]
    env_path.write_text("\n".join(values) + "\n", encoding="utf-8")
    command.upgrade(_alembic(), "head")
    print("Local operator token (shown once; store it in a password manager):")
    print(token)
    print("Created .env and migrated the local database. Never commit .env.")


def demo() -> None:
    from company_os.agents import execute

    samples: dict[str, dict[str, Any]] = {
        "engineering": {"event": "workflow_run", "repository": "demo/sample", "run_id": 42},
        "research": {
            "sources": [
                {"url": "https://example.test/source", "title": "Demo", "content": "untrusted source"}
            ]
        },
        "sales": {"prospect": {"domain": "example.test"}, "criteria": {"relevant": True}},
        "delivery": {"report": "Synthetic sample only", "evidence_reference": "demo-evidence"},
        "finance": {"entries": [{"kind": "income", "amount_micro_usd": 149000000, "verified": False}]},
    }
    print(json.dumps({kind: execute(kind, payload) for kind, payload in samples.items()}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="kozphy")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("setup", help="create a local .env, operator token and database")
    init.add_argument("--database-url", default="sqlite:///runtime/company.db")
    init.add_argument("--tenant", default="local")
    init.add_argument("--actor", default="operator")
    commands.add_parser("migrate", help="apply local database migrations")
    serve = commands.add_parser("api", help="run the local API and dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("worker", help="run the durable background worker")
    commands.add_parser("scheduler", help="run the durable interval scheduler")
    commands.add_parser("demo", help="print synthetic offline outputs for all five workflows")
    args = parser.parse_args()

    if args.command == "setup":
        setup(args.database_url, args.tenant, args.actor)
    elif args.command == "migrate":
        Settings()
        command.upgrade(_alembic(), "head")
    elif args.command == "api":
        uvicorn.run("company_os.api:create_app", factory=True, host=args.host, port=args.port)
    elif args.command == "worker":
        settings = Settings()
        from company_os.db import make_engine

        Worker(make_engine(settings.database_url), lease_seconds=settings.lease_seconds).run_forever()
    elif args.command == "scheduler":
        settings = Settings()
        from company_os.db import make_engine

        Scheduler(make_engine(settings.database_url), settings.tenant_budget_micro_usd).run_forever()
    elif args.command == "demo":
        demo()
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
