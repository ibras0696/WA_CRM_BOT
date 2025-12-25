"""split balances and add installment fields

Revision ID: 4d1e6b8b02a1
Revises: 37d59278e876
Create Date: 2025-12-24 16:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4d1e6b8b02a1"
down_revision = "37d59278e876"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Shift balances
    op.add_column(
        "shifts",
        sa.Column("opening_balance_cash", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "shifts",
        sa.Column("opening_balance_bank", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "shifts",
        sa.Column("current_balance_cash", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "shifts",
        sa.Column("current_balance_bank", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE shifts
            SET
                opening_balance_cash = opening_balance,
                current_balance_cash = current_balance,
                opening_balance_bank = 0,
                current_balance_bank = 0
            """
        )
    )
    op.alter_column("shifts", "opening_balance_cash", server_default=None)
    op.alter_column("shifts", "opening_balance_bank", server_default=None)
    op.alter_column("shifts", "current_balance_cash", server_default=None)
    op.alter_column("shifts", "current_balance_bank", server_default=None)

    # Deal type and installment fields
    deal_type_enum = sa.Enum("operation", "installment", name="deal_type")
    deal_type_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "deals",
        sa.Column(
            "deal_type",
            deal_type_enum,
            nullable=False,
            server_default="operation",
        ),
    )
    op.add_column("deals", sa.Column("product_price", sa.Numeric(12, 2)))
    op.add_column("deals", sa.Column("markup_percent", sa.Numeric(5, 2)))
    op.add_column("deals", sa.Column("markup_amount", sa.Numeric(12, 2)))
    op.add_column("deals", sa.Column("installment_term_months", sa.Integer()))
    op.add_column("deals", sa.Column("down_payment_amount", sa.Numeric(12, 2)))
    op.add_column("deals", sa.Column("installment_total_amount", sa.Numeric(12, 2)))
    op.add_column("deals", sa.Column("monthly_payment_amount", sa.Numeric(12, 2)))
    op.alter_column("deals", "deal_type", server_default=None)


def downgrade() -> None:
    op.drop_column("deals", "monthly_payment_amount")
    op.drop_column("deals", "installment_total_amount")
    op.drop_column("deals", "down_payment_amount")
    op.drop_column("deals", "installment_term_months")
    op.drop_column("deals", "markup_amount")
    op.drop_column("deals", "markup_percent")
    op.drop_column("deals", "product_price")
    op.drop_column("deals", "deal_type")
    op.execute("DROP TYPE IF EXISTS deal_type")

    op.drop_column("shifts", "current_balance_bank")
    op.drop_column("shifts", "current_balance_cash")
    op.drop_column("shifts", "opening_balance_bank")
    op.drop_column("shifts", "opening_balance_cash")
