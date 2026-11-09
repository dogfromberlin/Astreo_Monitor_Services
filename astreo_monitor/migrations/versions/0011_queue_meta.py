"""4.5: di quale allarme è ogni messaggio in coda (chiave, tipo di evento, stato), per i pulsanti di Telegram.

Revision ID: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notification_queue", sa.Column("meta", sa.Unicode(400)))


def downgrade():
    op.drop_column("notification_queue", "meta")
