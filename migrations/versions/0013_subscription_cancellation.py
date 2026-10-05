"""Add cancellation fields to Salon Pro subscriptions.

Revision ID: 0013_subscription_cancellation
Revises: 0012_rls_tenant_isolation
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_subscription_cancellation"
down_revision = "0012_rls_tenant_isolation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subscription",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "subscription",
        sa.Column("canceled_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column("subscription", "canceled_at")
    op.drop_column("subscription", "cancel_at_period_end")
