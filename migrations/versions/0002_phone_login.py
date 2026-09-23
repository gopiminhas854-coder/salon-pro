"""Add phone login to users."""
from alembic import op
import sqlalchemy as sa

revision = "0002_phone_login"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user", sa.Column("phone_number", sa.String(length=20), nullable=True))
    op.create_unique_constraint("uq_user_phone_number", "user", ["phone_number"])


def downgrade():
    op.drop_constraint("uq_user_phone_number", "user", type_="unique")
    op.drop_column("user", "phone_number")
