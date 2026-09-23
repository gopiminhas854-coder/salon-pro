"""Add commission rate to invoices for historical staff commission tracking."""
from alembic import op
import sqlalchemy as sa

revision = "0004_invoice_commission_rate"
down_revision = "0003_customer_dates"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoice", sa.Column("commission_rate", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("invoice", "commission_rate")
