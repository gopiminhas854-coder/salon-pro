"""Safe production migration entrypoint for Salon Pro.

Existing installations created before Alembic was introduced are stamped at the
baseline only after all baseline tables are present. Fresh databases are created
through the baseline migration. Future migrations always run through upgrade().
The application bootstrap runs only after migrations complete.
"""
from sqlalchemy import inspect
from flask_migrate import stamp, upgrade
from app import app, db, init_db

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
        # A table-name-only check can accept a corrupted/obsolete schema.
        # Compare actual columns against the SQLAlchemy model metadata before
        # stamping an existing database at the migration baseline.
        model_tables = {table.name: {column.name for column in table.columns} for table in db.metadata.sorted_tables}
        for table_name, expected_columns in model_tables.items():
            actual_columns = {column['name'] for column in inspector.get_columns(table_name)}
            missing_columns = expected_columns - actual_columns
            if missing_columns:
                raise RuntimeError(
                    f"Existing database schema mismatch in {table_name}; "
                    f"missing columns: {', '.join(sorted(missing_columns))}"
                )
        stamp(BASELINE)

    # Apply the schema first. This is the only migration/bootstrap path used by
    # Render before Gunicorn starts, so there is no concurrent init_db() race.
    upgrade()

    # Seed/repair application data only after the schema is fully migrated.
    # This also creates the default admin on a fresh database and backfills
    # invoice line items from older installations.
    init_db()
