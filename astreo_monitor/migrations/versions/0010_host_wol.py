"""4.4: Wake-on-LAN. Indirizzo MAC e broadcast scelti a mano per un server collegato (NULL = quelli inviati dall'agente).

Revision ID: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("hosts", sa.Column("wol_mac", sa.Unicode(17)))
    op.add_column("hosts", sa.Column("wol_broadcast", sa.Unicode(64)))


def downgrade():
    op.drop_column("hosts", "wol_broadcast")
    op.drop_column("hosts", "wol_mac")
