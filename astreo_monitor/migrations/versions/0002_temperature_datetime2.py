"""SQL Server: system_temperature.timestamp da DATETIME a DATETIME2(0), come le altre tabelle.

Il vecchio tipo DATETIME interpreta le date in base alla lingua del login; DATETIME2 no.
Sugli altri database non fa nulla.

Revision ID: 0002
"""
from alembic import op
from sqlalchemy import text

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "mssql":
        return
    tipo = bind.execute(text(
        "SELECT t.name FROM sys.columns c JOIN sys.types t ON t.user_type_id = c.user_type_id "
        "WHERE c.object_id = OBJECT_ID('dbo.system_temperature') AND c.name = 'timestamp'")).scalar()
    if tipo != "datetime":
        return
    has_ix = bind.execute(text("SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.system_temperature') "
                               "AND name = 'IX_system_temperature_ts'")).scalar()
    if has_ix:
        op.execute("DROP INDEX IX_system_temperature_ts ON dbo.system_temperature")
    op.execute("ALTER TABLE dbo.system_temperature ALTER COLUMN [timestamp] DATETIME2(0) NULL")
    op.execute("CREATE CLUSTERED INDEX IX_system_temperature_ts ON dbo.system_temperature ([timestamp])")


def downgrade():
    pass
