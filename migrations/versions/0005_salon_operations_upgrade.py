"""Salon Pro operations upgrade: scheduling, tips, staff breaks, packages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0005_salon_operations_upgrade"
down_revision = ("0003_billing_integrity", "0004_invoice_commission_rate")
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    with op.batch_alter_table("appointment") as batch_op:
        batch_op.add_column(sa.Column("recurrence_rule", sa.String(length=20), nullable=True, server_default="None"))
        batch_op.add_column(sa.Column("recurrence_end_date", sa.Date(), nullable=True))

    with op.batch_alter_table("invoice") as batch_op:
        batch_op.add_column(sa.Column("tip", sa.Float(), nullable=True, server_default="0"))

    inspector = inspect(bind)

    if not inspector.has_table("staff_schedule"):
        op.create_table(
            "staff_schedule",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
            sa.Column("day_of_week", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.String(length=5), nullable=True, server_default="09:00"),
            sa.Column("end_time", sa.String(length=5), nullable=True, server_default="20:00"),
            sa.Column("is_working", sa.Boolean(), nullable=True, server_default=sa.true()),
        )

    if not inspector.has_table("staff_break"):
        op.create_table(
            "staff_break",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
            sa.Column("day_of_week", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.String(length=5), nullable=False),
            sa.Column("end_time", sa.String(length=5), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )

    if not inspector.has_table("salon_package"):
        op.create_table(
            "salon_package",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("package_type", sa.String(length=20), nullable=True, server_default="Package"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("price", sa.Float(), nullable=True, server_default="0"),
            sa.Column("total_uses", sa.Integer(), nullable=True, server_default="1"),
            sa.Column("validity_days", sa.Integer(), nullable=True, server_default="30"),
            sa.Column("included_services", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("customer_package"):
        op.create_table(
            "customer_package",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=False),
            sa.Column("package_id", sa.Integer(), sa.ForeignKey("salon_package.id"), nullable=False),
            sa.Column("purchased_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.Date(), nullable=False),
            sa.Column("uses_total", sa.Integer(), nullable=True, server_default="1"),
            sa.Column("uses_used", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("prepaid_balance", sa.Float(), nullable=True, server_default="0"),
            sa.Column("status", sa.String(length=20), nullable=True, server_default="Active"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("staff_schedule"):
        op.drop_table("staff_schedule")
    if inspector.has_table("customer_package"):
        op.drop_table("customer_package")
    if inspector.has_table("salon_package"):
        op.drop_table("salon_package")
    if inspector.has_table("staff_break"):
        op.drop_table("staff_break")

    with op.batch_alter_table("invoice") as batch_op:
        batch_op.drop_column("tip")
    with op.batch_alter_table("appointment") as batch_op:
        batch_op.drop_column("recurrence_end_date")
        batch_op.drop_column("recurrence_rule")
