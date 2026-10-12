from alembic import context

from company_os.config import Settings
from company_os.db import make_engine
from company_os.schema import metadata

engine = make_engine(Settings().database_url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()
