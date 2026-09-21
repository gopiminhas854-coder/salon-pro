"""Add the user-to-staff account link table.

Revision ID: 0002_user_staff_link
Revises: 0001_initial_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_user_staff_link"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_staff_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("staff_id"),
    )


def downgrade():
    op.drop_table("user_staff_link")
