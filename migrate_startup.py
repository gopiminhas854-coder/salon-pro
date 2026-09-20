"""Safe production migration entrypoint for Salon Pro.

Existing installations created before Alembic was introduced are stamped at the
baseline only after all baseline tables are present. Fresh databases are created
through the baseline migration. Future migrations always run through upgrade().
"""
from sqlalchemy import inspect
from flask_migrate import stamp, upgrade
from app import app, db

BASELINE = "0001_initial_schema"
EXPECTED_TABLES = {
    "user", "customer", "service", "staff", "appointment", "expense",
    "inventory_item", "invoice", "staff_commission", "staff_attendance",
    "customer_loyalty", "inventory_sale", "supplier", "inventory_transaction",
    "inventory_purchase", "invoice_item", "inventory_sale_line",
    "loyalty_transaction", "salon_hours", "salon_closure", "salon_setting",
    "invoice_refund", "invoice_payment",
}

with app.app_context():
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - tables
    has_version = "alembic_version" in tables

    if not has_version and tables:
        if missing:
            raise RuntimeError(
                "Existing database is not compatible with the Salon Pro migration "
                f"baseline; missing tables: {', '.join(sorted(missing))}"
            )
        stamp(BASELINE)

    upgrade()
