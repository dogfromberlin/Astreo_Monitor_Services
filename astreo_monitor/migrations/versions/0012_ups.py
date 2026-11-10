"""4.6: UPS. Elenco degli UPS controllati e storico delle letture (un campione al minuto, 90 giorni).

Revision ID: 0012
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TS = sa.DateTime().with_variant(mssql.DATETIME2(precision=0), "mssql")


def upgrade():
    op.create_table(
        "ups_devices",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("name", sa.Unicode(100), nullable=False),
        sa.Column("backend", sa.String(16), nullable=False),
        sa.Column("host", sa.Unicode(255), nullable=False),
        sa.Column("port", sa.Integer()),
        sa.Column("ups_name", sa.Unicode(100)),
        sa.Column("community", sa.Unicode(100)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_ups_devices", mssql_clustered=False),
    )
    op.create_table(
        "ups_samples",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("ups_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", TS, nullable=False),
        sa.Column("status", sa.String(16)),
        sa.Column("charge", sa.Float()), sa.Column("runtime_s", sa.Float()), sa.Column("load", sa.Float()),
        sa.Column("input_v", sa.Float()), sa.Column("output_v", sa.Float()),
        sa.PrimaryKeyConstraint("id", name="PK_ups_samples", mssql_clustered=False),
    )
    op.create_index("IX_ups_samples_ts", "ups_samples", ["timestamp"], mssql_clustered=True)
    op.create_index("IX_ups_samples_ups", "ups_samples", ["ups_id", "timestamp"])


def downgrade():
    op.drop_table("ups_samples")
    op.drop_table("ups_devices")
