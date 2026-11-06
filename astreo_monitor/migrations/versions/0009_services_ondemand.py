"""4.3: servizi "discontinui" (partono solo quando servono): fermi non sono un guasto, niente avvisi.

hosts.services_ondemand: servizi discontinui di un server collegato (stesso formato di hosts.services);
monitored_services.ondemand: lo stesso per i servizi del server centrale.

Revision ID: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("hosts", sa.Column("services_ondemand", sa.Unicode(2000)))
    op.add_column("monitored_services", sa.Column("ondemand", sa.Boolean(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("monitored_services", "ondemand", mssql_drop_default=True)
    op.drop_column("hosts", "services_ondemand")
