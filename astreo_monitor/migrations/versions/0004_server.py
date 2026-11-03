"""4.0: più server. Tabella hosts (1 = server centrale) e colonna host_id su metriche, temperature ed eventi.

I dati esistenti restano validi: la colonna ha valore predefinito 1, cioè il server centrale.

Revision ID: 0004
"""
import datetime as dt
import socket

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TS = sa.DateTime().with_variant(mssql.DATETIME2(precision=0), "mssql")
TABLES = ("system_metrics", "system_temperature", "events")


def upgrade():
    hosts = op.create_table(
        "hosts",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("name", sa.Unicode(100), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("token_hash", sa.String(64)),
        sa.Column("services", sa.Unicode(2000)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen", TS),
        sa.Column("agent_version", sa.String(32)),
        sa.Column("os_info", sa.Unicode(200)),
        sa.PrimaryKeyConstraint("id", name="PK_hosts", mssql_clustered=False),
    )
    op.create_index("UX_hosts_token", "hosts", ["token_hash"], unique=True,
                    mssql_where=sa.text("token_hash IS NOT NULL"), postgresql_where=sa.text("token_hash IS NOT NULL"),
                    sqlite_where=sa.text("token_hash IS NOT NULL"))
    # il server centrale è sempre la riga 1 (tabella appena creata: il primo id è 1 su tutti i database)
    op.bulk_insert(hosts, [{"name": socket.gethostname()[:100], "kind": "local", "enabled": True, "sort_order": 0,
                            "created_at": dt.datetime.now().replace(microsecond=0)}])
    for table in TABLES:
        op.add_column(table, sa.Column("host_id", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("IX_system_metrics_host", "system_metrics", ["host_id", "timestamp"])
    op.create_index("IX_system_temperature_host", "system_temperature", ["host_id", "timestamp"])


def downgrade():
    op.drop_index("IX_system_temperature_host", "system_temperature")
    op.drop_index("IX_system_metrics_host", "system_metrics")
    for table in TABLES:
        op.drop_column(table, "host_id", mssql_drop_default=True)
    op.drop_index("UX_hosts_token", "hosts")
    op.drop_table("hosts")
