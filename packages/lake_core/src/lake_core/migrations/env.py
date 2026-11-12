from alembic import context
from sqlalchemy import create_engine

url = context.config.get_main_option("sqlalchemy.url")
assert url
engine = create_engine(url)
with engine.connect() as conn:
    context.configure(connection=conn)
    with context.begin_transaction():
        context.run_migrations()
