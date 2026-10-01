"""Colour Lab: client diagnosis, formulas and before/after records.

Revision ID: 0011_colour_lab
Revises: 0010_multi_tenant_isolation
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_colour_lab"
down_revision = "0010_multi_tenant_isolation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "colour_case",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account_profile.id"), nullable=True, index=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True, index=True),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=True, index=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("service_type", sa.String(80)),
        sa.Column("current_hair_type", sa.String(40)),
        sa.Column("current_level", sa.String(20)),
        sa.Column("current_tone", sa.String(80)),
        sa.Column("hair_history", sa.Text()),
        sa.Column("hair_condition", sa.String(80)),
        sa.Column("target_level", sa.String(20)),
        sa.Column("target_tone", sa.String(100)),
        sa.Column("technique", sa.String(80)),
        sa.Column("brand", sa.String(100)),
        sa.Column("developer", sa.String(60)),
        sa.Column("developer_strength", sa.String(40)),
        sa.Column("mixing_ratio", sa.String(60)),
        sa.Column("processing_minutes", sa.Integer()),
        sa.Column("application_notes", sa.Text()),
        sa.Column("result_rating", sa.String(40)),
        sa.Column("result_notes", sa.Text()),
        sa.Column("next_time_notes", sa.Text()),
        sa.Column("before_photo_data", sa.Text()),
        sa.Column("after_photo_data", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_colour_case_account_created", "colour_case", ["account_id", "created_at"])

    op.create_table(
        "colour_formula_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account_profile.id"), nullable=True, index=True),
        sa.Column("colour_case_id", sa.Integer(), sa.ForeignKey("colour_case.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), nullable=True, index=True),
        sa.Column("product_name", sa.String(150), nullable=False),
        sa.Column("brand", sa.String(100)),
        sa.Column("shade_code", sa.String(60)),
        sa.Column("quantity_grams", sa.Float(), default=0),
        sa.Column("developer", sa.String(60)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_colour_formula_account_case", "colour_formula_item", ["account_id", "colour_case_id"])


def downgrade():
    op.drop_index("ix_colour_formula_account_case", table_name="colour_formula_item")
    op.drop_table("colour_formula_item")
    op.drop_index("ix_colour_case_account_created", table_name="colour_case")
    op.drop_table("colour_case")
