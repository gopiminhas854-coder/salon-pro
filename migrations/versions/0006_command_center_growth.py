"""Salon Pro command center and growth features."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_command_center_growth"
down_revision = "0005_salon_operations_upgrade"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    with op.batch_alter_table("service") as batch_op:
        batch_op.add_column(sa.Column("retention_min_days", sa.Integer(), nullable=True, server_default="30"))
        batch_op.add_column(sa.Column("retention_max_days", sa.Integer(), nullable=True, server_default="45"))

    with op.batch_alter_table("salon_setting") as batch_op:
        batch_op.add_column(sa.Column("invoice_prefix", sa.String(length=20), nullable=True, server_default="SP"))
        batch_op.add_column(sa.Column("gst_number", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("logo_data_url", sa.Text(), nullable=True))

    if not inspector.has_table("whatsapp_template"):
        op.create_table(
            "whatsapp_template",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=40), nullable=False, unique=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("gift_card"):
        op.create_table(
            "gift_card",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(length=40), nullable=False, unique=True),
            sa.Column("purchaser_customer_id", sa.Integer(), sa.ForeignKey("customer.id")),
            sa.Column("recipient_name", sa.String(length=120)),
            sa.Column("original_amount", sa.Float(), nullable=False),
            sa.Column("balance", sa.Float(), nullable=False),
            sa.Column("expires_at", sa.Date()),
            sa.Column("status", sa.String(length=20), nullable=True, server_default="Active"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("gift_card_transaction"):
        op.create_table(
            "gift_card_transaction",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("gift_card_id", sa.Integer(), sa.ForeignKey("gift_card.id"), nullable=False),
            sa.Column("transaction_type", sa.String(length=20), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoice.id")),
            sa.Column("notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("audit_log"):
        op.create_table(
            "audit_log",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id")),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column("path", sa.String(length=255)),
            sa.Column("details", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    for table in ("audit_log","gift_card_transaction","gift_card","whatsapp_template"):
        if inspector.has_table(table):
            op.drop_table(table)
    with op.batch_alter_table("salon_setting") as batch_op:
        batch_op.drop_column("logo_data_url")
        batch_op.drop_column("gst_number")
        batch_op.drop_column("invoice_prefix")
    with op.batch_alter_table("service") as batch_op:
        batch_op.drop_column("retention_max_days")
        batch_op.drop_column("retention_min_days")
