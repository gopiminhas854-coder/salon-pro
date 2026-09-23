"""Configurable loyalty rewards."""
from alembic import op
import sqlalchemy as sa

revision = "0009_loyalty_rewards"
down_revision = "0008_roles_backup_history"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("salon_setting") as batch_op:
        batch_op.add_column(sa.Column("loyalty_reward_threshold", sa.Integer(), nullable=True, server_default="1000"))
        batch_op.add_column(sa.Column("loyalty_reward_value", sa.Float(), nullable=True, server_default="500"))

def downgrade():
    with op.batch_alter_table("salon_setting") as batch_op:
        batch_op.drop_column("loyalty_reward_value")
        batch_op.drop_column("loyalty_reward_threshold")
