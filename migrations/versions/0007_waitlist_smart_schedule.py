"""Waitlist and smart scheduling."""
from alembic import op
import sqlalchemy as sa

revision = "0007_waitlist_smart_schedule"
down_revision = "0006_command_center_growth"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "waitlist_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("service.id"), nullable=False),
        sa.Column("preferred_staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=True),
        sa.Column("preferred_date", sa.Date(), nullable=True),
        sa.Column("preferred_time", sa.String(length=5), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Open"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

def downgrade():
    op.drop_table("waitlist_entry")
