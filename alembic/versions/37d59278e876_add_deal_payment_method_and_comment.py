"""add deal payment method and comment

Revision ID: 37d59278e876
Revises: 77cb65890393
Create Date: 2025-12-23 23:46:06.027993

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '37d59278e876'
down_revision = '77cb65890393'
branch_labels = None
depends_on = None


def upgrade() -> None:
    payment_enum = sa.Enum(
        "cash",
        "bank",
        name="deal_payment_method",
    )
    payment_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "deals",
        sa.Column(
            "payment_method",
            payment_enum,
            nullable=False,
            server_default="cash",
        ),
    )
    op.add_column(
        "deals",
        sa.Column(
            "comment",
            sa.String(length=255),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("deals", "comment")
    op.drop_column("deals", "payment_method")
    op.execute("DROP TYPE IF EXISTS deal_payment_method")
