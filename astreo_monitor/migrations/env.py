"""Ambiente Alembic: usato da astreo_monitor.migrate (non dalla riga di comando di alembic)."""
from alembic import context

from astreo_monitor import models

connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=models.metadata, compare_type=False,
                  transaction_per_migration=True)
with context.begin_transaction():
    context.run_migrations()
