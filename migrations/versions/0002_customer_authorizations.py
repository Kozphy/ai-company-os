"""Persist operator-reviewed customer authorization scope."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the customer authorization table when it is absent."""
    bind = op.get_bind()
    if sa.inspect(bind).has_table("authorizations"):
        return
    op.create_table(
        "authorizations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("repository", sa.String(160), nullable=False),
        sa.Column("customer_name", sa.String(256), nullable=False),
        sa.Column("signer_name", sa.String(256), nullable=False),
        sa.Column("window_start", sa.String(10), nullable=False),
        sa.Column("window_end", sa.String(10), nullable=False),
        sa.Column("authorization_digest", sa.String(64), nullable=False),
        sa.Column("scope_digest", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("authorized_at", sa.Float, nullable=False),
        sa.Column("expires_at", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revoked_at", sa.Float),
        sa.CheckConstraint("window_start <= window_end", name="ck_auth_window_order"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name="ck_auth_status"),
    )
    op.create_index("ix_authorizations_tenant_id", "authorizations", ["tenant_id"])


def downgrade() -> None:
    """Drop the customer authorization table and its tenant index."""
    bind = op.get_bind()
    if sa.inspect(bind).has_table("authorizations"):
        op.drop_index("ix_authorizations_tenant_id", table_name="authorizations")
        op.drop_table("authorizations")
