"""Add phone login to users."""
from alembic import op
import sqlalchemy as sa

revision = "0002_phone_login"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    # Batch mode keeps this migration portable across SQLite and PostgreSQL.
    with op.batch_alter_table("user") as batch_op:
        batch_op.add_column(sa.Column("phone_number", sa.String(length=20), nullable=True))
        batch_op.create_unique_constraint("uq_user_phone_number", ["phone_number"])


def downgrade():
    with op.batch_alter_table("user") as batch_op:
        batch_op.drop_constraint("uq_user_phone_number", type_="unique")
        batch_op.drop_column("phone_number")
