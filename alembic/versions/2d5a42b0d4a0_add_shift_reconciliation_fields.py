"""Add shift reconciliation fields.

Revision ID: 2d5a42b0d4a0
Revises: 4d1e6b8b02a1
Create Date: 2025-12-25 19:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2d5a42b0d4a0"
down_revision = "4d1e6b8b02a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shifts", sa.Column("reported_cash", sa.Numeric(12, 2)))
    op.add_column("shifts", sa.Column("reported_bank", sa.Numeric(12, 2)))
    op.add_column("shifts", sa.Column("reported_at", sa.DateTime(timezone=True)))
    op.add_column("shifts", sa.Column("cash_diff", sa.Numeric(12, 2)))
    op.add_column("shifts", sa.Column("bank_diff", sa.Numeric(12, 2)))


def downgrade() -> None:
    op.drop_column("shifts", "bank_diff")
    op.drop_column("shifts", "cash_diff")
    op.drop_column("shifts", "reported_at")
    op.drop_column("shifts", "reported_bank")
    op.drop_column("shifts", "reported_cash")
