"""4.3: permessi per server. allow_commands: avvia / ferma / riavvia i servizi dalla dashboard;
allow_update: aggiornamento dell'agente dalla dashboard. Spenti di serie: servono anche sull'agente.

Revision ID: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("hosts", sa.Column("allow_commands", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("hosts", sa.Column("allow_update", sa.Boolean(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("hosts", "allow_update", mssql_drop_default=True)
    op.drop_column("hosts", "allow_commands", mssql_drop_default=True)
