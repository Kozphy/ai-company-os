"""Process settings loaded from the environment and an optional ``.env`` file."""

import json
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Local and test runtime settings.

    Production is rejected. Identity keys must be SHA-256 hex digests of
    bearer tokens. Each identity maps to ``tenant_id``, ``actor_id``, and
    ``role``.

    Attributes:
        environment: ``local`` or ``test``. ``production`` is invalid.
        database_url: SQLAlchemy database URL.
        identities_json: JSON object of token-hash to identity mappings.
        webhook_secret: HMAC secret for GitHub webhooks. Empty disables ingestion.
        webhook_routes_json: JSON object mapping ``owner/name`` to
            ``tenant_id`` and ``actor_id``.
        lease_seconds: Worker lease length.
        concurrency_limit: Reserved worker concurrency bound.
        tenant_budget_micro_usd: Default tenant budget in millionths of a USD.
    """

    model_config = SettingsConfigDict(env_prefix="KOZPHY_", env_file=".env", extra="ignore")
    environment: Literal["local", "test", "production"] = "local"
    database_url: str = Field(default="sqlite:///runtime/company.db", repr=False)
    identities_json: str = Field(default="{}", repr=False)
    webhook_secret: str = Field(default="", repr=False)
    webhook_routes_json: str = "{}"
    lease_seconds: int = Field(default=60, ge=5, le=3600)
    concurrency_limit: int = Field(default=2, ge=1, le=32)
    tenant_budget_micro_usd: int = Field(default=1_000_000, ge=0)

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        """Reject production mode and malformed identity maps.

        Returns:
            This settings instance.

        Raises:
            ValueError: The JSON is invalid, the environment is production,
                or an identity key, field set, role, or id is invalid.
        """
        if self.environment == "production":
            raise ValueError("production requires verified OIDC/TLS/managed secrets; unavailable")
        identities = json.loads(self.identities_json)
        if not isinstance(identities, dict):
            raise ValueError("identity mapping must be an object")
        for token_hash, identity in identities.items():
            if len(token_hash) != 64 or any(c not in "0123456789abcdef" for c in token_hash):
                raise ValueError("identity keys must be SHA256 token hashes")
            if set(identity) != {"tenant_id", "actor_id", "role"}:
                raise ValueError("identity fields invalid")
            if identity["role"] not in {"operator", "member", "reader"}:
                raise ValueError("role invalid")
            if not identity["tenant_id"] or not identity["actor_id"]:
                raise ValueError("identity incomplete")
        return self
