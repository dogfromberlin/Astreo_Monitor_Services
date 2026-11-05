"""4.2: soglie di CPU e memoria per server (NULL = soglia generale delle impostazioni).

Revision ID: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

FLOATS = ("cpu_warning", "cpu_alert", "mem_warning", "mem_alert")


def upgrade():
    for c in FLOATS:
        op.add_column("hosts", sa.Column(c, sa.Float()))


def downgrade():
    for c in reversed(FLOATS):
        op.drop_column("hosts", c)
