"""Initial immutable schema. Backup before downgrade (destroys state)."""

from alembic import op

from company_os.schema import control, metadata

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())
    op.get_bind().execute(control.insert().values(id=1, stopped=False))


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
