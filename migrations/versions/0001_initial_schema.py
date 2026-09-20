"""Initial Salon Pro schema.

Revision ID: 0001_initial_schema
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20)),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "customer",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=100)),
        sa.Column("gender", sa.String(length=10)),
        sa.Column("address", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "service",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("duration_minutes", sa.Integer()),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("category", sa.String(length=50)),
        sa.Column("is_active", sa.Boolean()),
    )
    op.create_table(
        "staff",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=20)),
        sa.Column("email", sa.String(length=100)),
        sa.Column("specialty", sa.String(length=100)),
        sa.Column("is_active", sa.Boolean()),
    )
    op.create_table(
        "appointment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("service.id"), nullable=False),
        sa.Column("appointment_date", sa.Date(), nullable=False),
        sa.Column("appointment_time", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "expense",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "inventory_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("sku", sa.String(length=50)),
        sa.Column("category", sa.String(length=60)),
        sa.Column("stock_qty", sa.Float()),
        sa.Column("reorder_level", sa.Float()),
        sa.Column("cost_price", sa.Float()),
        sa.Column("sale_price", sa.Float()),
        sa.Column("is_active", sa.Boolean()),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("sku"),
    )
    op.create_table(
        "invoice",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointment.id"), unique=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id")),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("discount", sa.Float()),
        sa.Column("tax", sa.Float()),
        sa.Column("total", sa.Float(), nullable=False),
        sa.Column("payment_status", sa.String(length=20)),
        sa.Column("payment_method", sa.String(length=30)),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "staff_commission",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("commission_rate", sa.Float()),
        sa.Column("commission_type", sa.String(length=20)),
        sa.UniqueConstraint("staff_id"),
    )
    op.create_table(
        "staff_attendance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("attendance_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20)),
        sa.Column("check_in", sa.String(length=10)),
        sa.Column("check_out", sa.String(length=10)),
        sa.Column("notes", sa.Text()),
    )
    op.create_table(
        "customer_loyalty",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("points", sa.Integer()),
        sa.Column("lifetime_spend", sa.Float()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("customer_id"),
    )
    op.create_table(
        "inventory_sale",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoice.id"), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "supplier",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=30)),
        sa.Column("email", sa.String(length=100)),
        sa.Column("address", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("is_active", sa.Boolean()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "inventory_transaction",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), nullable=False),
        sa.Column("transaction_type", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit_cost", sa.Float()),
        sa.Column("reference", sa.String(length=120)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id")),
    )
    op.create_table(
        "inventory_purchase",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier.id")),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit_cost", sa.Float(), nullable=False),
        sa.Column("total_cost", sa.Float(), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=120)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "invoice_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoice.id"), nullable=False),
        sa.Column("description", sa.String(length=150), nullable=False),
        sa.Column("quantity", sa.Float()),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("total", sa.Float(), nullable=False),
    )
    op.create_table(
        "inventory_sale_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory_sale_id", sa.Integer(), sa.ForeignKey("inventory_sale.id"), nullable=False),
        sa.Column("invoice_item_id", sa.Integer(), sa.ForeignKey("invoice_item.id"), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.UniqueConstraint("inventory_sale_id"),
        sa.UniqueConstraint("invoice_item_id"),
    )
    op.create_table(
        "loyalty_transaction",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("transaction_type", sa.String(length=30), nullable=False),
        sa.Column("reference", sa.String(length=120)),
        sa.Column("amount", sa.Float()),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("reference"),
    )
    op.create_table(
        "salon_hours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("open_time", sa.String(length=5)),
        sa.Column("close_time", sa.String(length=5)),
        sa.Column("is_closed", sa.Boolean()),
        sa.UniqueConstraint("day_of_week"),
    )
    op.create_table(
        "salon_closure",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("closure_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=200)),
        sa.UniqueConstraint("closure_date"),
    )
    op.create_table(
        "salon_setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("salon_name", sa.String(length=120)),
        sa.Column("phone", sa.String(length=30)),
        sa.Column("address", sa.Text()),
        sa.Column("tax_rate", sa.Float()),
        sa.Column("loyalty_rate", sa.Float()),
        sa.Column("reminder_days", sa.Integer()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_table(
        "invoice_refund",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoice.id"), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("refund_method", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_table(
        "invoice_payment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoice.id"), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )


def downgrade():
    op.drop_table("invoice_payment")
    op.drop_table("invoice_refund")
    op.drop_table("salon_setting")
    op.drop_table("salon_closure")
    op.drop_table("salon_hours")
    op.drop_table("loyalty_transaction")
    op.drop_table("inventory_sale_line")
    op.drop_table("invoice_item")
    op.drop_table("inventory_purchase")
    op.drop_table("inventory_transaction")
    op.drop_table("supplier")
    op.drop_table("inventory_sale")
    op.drop_table("customer_loyalty")
    op.drop_table("staff_attendance")
    op.drop_table("staff_commission")
    op.drop_table("invoice")
    op.drop_table("inventory_item")
    op.drop_table("expense")
    op.drop_table("appointment")
    op.drop_table("staff")
    op.drop_table("service")
    op.drop_table("customer")
    op.drop_table("user")
