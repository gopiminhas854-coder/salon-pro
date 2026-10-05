"""Create the missing subscription base table and add cancellation fields.

The application model has always included subscriptions, but the historical
migration chain did not create the table on a fresh database. This migration
is defensive: it creates the base table when absent, then adds the cancellation
columns only when those columns are absent.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_subscription_cancellation"
down_revision = "0012_rls_tenant_isolation"
branch_labels = None
depends_on = None


def _column_names():
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("subscription")}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "subscription" not in inspector.get_table_names():
        op.create_table(
            "subscription",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("plan_key", sa.String(length=40), nullable=False, server_default="monthly"),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("amount_paise", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
            sa.Column("start_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("razorpay_order_id", sa.String(length=120), nullable=True),
            sa.Column("razorpay_payment_id", sa.String(length=120), nullable=True),
            sa.Column("razorpay_signature", sa.String(length=255), nullable=True),
            sa.Column("webhook_received", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("canceled_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("razorpay_order_id", name="uq_subscription_razorpay_order_id"),
            sa.UniqueConstraint("razorpay_payment_id", name="uq_subscription_razorpay_payment_id"),
        )
        op.create_index("ix_subscription_user_id", "subscription", ["user_id"], unique=False)
        return

    columns = _column_names()
    if "cancel_at_period_end" not in columns:
        op.add_column(
            "subscription",
            sa.Column(
                "cancel_at_period_end",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "canceled_at" not in columns:
        op.add_column(
            "subscription",
            sa.Column("canceled_at", sa.DateTime(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "subscription" not in inspector.get_table_names():
        return
    columns = _column_names()
    if "canceled_at" in columns:
        op.drop_column("subscription", "canceled_at")
    if "cancel_at_period_end" in columns:
        op.drop_column("subscription", "cancel_at_period_end")
