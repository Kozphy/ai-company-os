"""Initial immutable schema. Backup before downgrade (destroys state)."""

import sqlalchemy as sa
from alembic import op

from company_os.schema import control, metadata

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

V1_TABLES = (
    "control",
    "budgets",
    "flags",
    "payloads",
    "jobs",
    "events",
    "evidence",
    "evaluations",
    "approvals",
    "audit",
    "outbox",
    "ledger",
    "prospects",
    "schedules",
)


def upgrade() -> None:
    version_one = sa.MetaData()
    for table_name in V1_TABLES:
        metadata.tables[table_name].to_metadata(version_one)
    version_one.create_all(op.get_bind())
    op.get_bind().execute(control.insert().values(id=1, stopped=False))


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(V1_TABLES):
        metadata.tables[table_name].drop(bind, checkfirst=True)
