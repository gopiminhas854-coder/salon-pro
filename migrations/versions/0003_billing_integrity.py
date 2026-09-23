"""Harden historical billing and attendance integrity.

Revision ID: 0003_billing_integrity
Revises: 0002_user_staff_link
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "0003_billing_integrity"
down_revision = "0002_user_staff_link"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "invoice" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("invoice")}
        if "commission_rate" not in cols:
            op.add_column("invoice", sa.Column("commission_rate", sa.Float(), nullable=True))

        # Preserve historical reporting for old invoices by snapshotting the
        # commission rate that exists now. Future invoices snapshot at creation.
        bind.execute(text("""
            UPDATE invoice
            SET commission_rate = COALESCE(
                (SELECT sc.commission_rate
                 FROM staff_commission sc
                 JOIN appointment a ON a.staff_id = sc.staff_id
                 WHERE a.id = invoice.appointment_id),
                0
            )
            WHERE commission_rate IS NULL
        """))

    if "staff_attendance" in inspector.get_table_names():
        # Remove duplicate legacy rows before adding the uniqueness guarantee.
        bind.execute(text("""
            DELETE FROM staff_attendance
            WHERE id IN (
                SELECT newer.id
                FROM staff_attendance newer
                JOIN staff_attendance older
                  ON newer.staff_id = older.staff_id
                 AND newer.attendance_date = older.attendance_date
                 AND newer.id > older.id
            )
        """))
        indexes = {i["name"] for i in inspect(bind).get_indexes("staff_attendance")}
        if "uq_staff_attendance_staff_date" not in indexes:
            op.create_index(
                "uq_staff_attendance_staff_date",
                "staff_attendance",
                ["staff_id", "attendance_date"],
                unique=True,
            )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "staff_attendance" in inspector.get_table_names():
        indexes = {i["name"] for i in inspect(bind).get_indexes("staff_attendance")}
        if "uq_staff_attendance_staff_date" in indexes:
            op.drop_index("uq_staff_attendance_staff_date", table_name="staff_attendance")
    if "invoice" in inspector.get_table_names():
        cols = {c["name"] for c in inspect(bind).get_columns("invoice")}
        if "commission_rate" in cols:
            op.drop_column("invoice", "commission_rate")
