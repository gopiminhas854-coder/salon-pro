"""Staff roles and backup history."""
from alembic import op
import sqlalchemy as sa

revision = "0008_roles_backup_history"
down_revision = "0007_waitlist_smart_schedule"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "backup_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_name", sa.String(length=180), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
    )

def downgrade():
    op.drop_table("backup_log")
