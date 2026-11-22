import os

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import create_engine, pool

from keitaro_wrapper.database import Base

config = context.config
url: str | None = config.attributes.get("database_url")
if url is None:
    url = os.getenv("DATABASE_URL") or dotenv_values(".env").get("DATABASE_URL")
if not url:
    url = config.get_main_option("sqlalchemy.url")
if not url:
    raise RuntimeError("Database URL is not configured.")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
