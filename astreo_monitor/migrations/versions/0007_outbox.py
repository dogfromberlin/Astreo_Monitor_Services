"""4.2.1: la coda delle notifiche diventa anche la "posta in uscita" di tutti gli avvisi.

La colonna quiet distingue gli avvisi trattenuti dalla fascia di silenzio (recapitati insieme all'orario scelto)
da quelli da inviare subito, appena la transazione del job è confermata. I messaggi ancora in coda prima
dell'aggiornamento erano tutti della fascia di silenzio.

Revision ID: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notification_queue", sa.Column("quiet", sa.Boolean(), nullable=False, server_default="0"))
    q = sa.table("notification_queue", sa.column("quiet", sa.Boolean()), sa.column("sent_at", sa.DateTime()))
    op.execute(q.update().where(q.c.sent_at.is_(None)).values(quiet=True))


def downgrade():
    op.drop_column("notification_queue", "quiet", mssql_drop_default=True)
