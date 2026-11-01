"""3.2: tabelle dei controlli di altri dispositivi e servizi.

Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TS = sa.DateTime().with_variant(mssql.DATETIME2(precision=0), "mssql")


def upgrade():
    op.create_table(
        "checks",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("name", sa.Unicode(100), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("target", sa.Unicode(400), nullable=False),
        sa.Column("port", sa.Integer()),
        sa.Column("interval_s", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("timeout_s", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("retries", sa.SmallInteger(), nullable=False, server_default="2"),
        sa.Column("expect_status", sa.String(40)),
        sa.Column("keyword", sa.Unicode(200)),
        sa.Column("verify_tls", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("cert_warning_days", sa.SmallInteger(), nullable=False, server_default="14"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_checks", mssql_clustered=False),
    )
    op.create_table(
        "check_results",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("timestamp", TS, nullable=False),
        sa.Column("check_id", ID, nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("detail", sa.Unicode(300)),
        sa.PrimaryKeyConstraint("id", name="PK_check_results", mssql_clustered=False),
    )
    op.create_index("IX_check_results_ts", "check_results", ["timestamp", "check_id"], mssql_clustered=True)


def downgrade():
    op.drop_index("IX_check_results_ts", "check_results")
    op.drop_table("check_results")
    op.drop_table("checks")
