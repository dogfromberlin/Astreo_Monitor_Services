"""4.2: impostazioni per server. Soglie di disco e temperatura, avviso se non raggiungibile, minuti di attesa.

Le colonne vuote (NULL) significano "usa l'impostazione generale": i server esistenti si comportano come prima.

Revision ID: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

FLOATS = ("disk_warning", "disk_alert", "temp_warning", "temp_alert")


def upgrade():
    op.add_column("hosts", sa.Column("notify_offline", sa.Boolean(), nullable=False, server_default="1"))
    op.add_column("hosts", sa.Column("offline_minutes", sa.Integer()))
    for c in FLOATS:
        op.add_column("hosts", sa.Column(c, sa.Float()))


def downgrade():
    for c in reversed(FLOATS):
        op.drop_column("hosts", c)
    op.drop_column("hosts", "offline_minutes")
    op.drop_column("hosts", "notify_offline", mssql_drop_default=True)
