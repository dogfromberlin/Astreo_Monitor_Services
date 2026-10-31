"""Schema iniziale della 3.0 (equivalente agli script sql/001-009 delle versioni 2.x).

Su un database 2.x esistente questa migrazione NON viene eseguita: migrate.py la registra
come già applicata (stamp) dopo aver verificato che le tabelle ci siano tutte.

Revision ID: 0001
"""
from alembic import op

from astreo_monitor.migrations import schema_v1

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    schema_v1.metadata.create_all(op.get_bind())


def downgrade():
    schema_v1.metadata.drop_all(op.get_bind())
