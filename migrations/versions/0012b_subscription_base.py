"""Create the Salon Pro subscription table when missing.

This sits between tenant isolation (0012) and subscription cancellation
(0013). Some existing databases already contain the table; the migration
therefore creates it only when a fresh database does not.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012b_subscription_base"
down_revision = "0012_rls_tenant_isolation"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "subscription" in inspector.get_table_names():
        return

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
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("razorpay_order_id", name="uq_subscription_razorpay_order_id"),
        sa.UniqueConstraint("razorpay_payment_id", name="uq_subscription_razorpay_payment_id"),
    )
    op.create_index("ix_subscription_user_id", "subscription", ["user_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "subscription" not in inspector.get_table_names():
        return
    op.drop_index("ix_subscription_user_id", table_name="subscription")
    op.drop_table("subscription")
