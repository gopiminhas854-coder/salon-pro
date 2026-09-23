"""Add customer birthday and anniversary dates."""
from alembic import op
import sqlalchemy as sa

revision = "0003_customer_dates"
down_revision = "0002_phone_login"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customer", sa.Column("date_of_birth", sa.Date(), nullable=True))
    op.add_column("customer", sa.Column("anniversary_date", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("customer", "anniversary_date")
    op.drop_column("customer", "date_of_birth")
