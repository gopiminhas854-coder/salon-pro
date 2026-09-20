# Database safety

Salon Pro uses SQLAlchemy `create_all()` for additive schema creation. It does **not** drop existing tables or rows. New releases in this repository add new tables rather than replacing existing data.

Before a production upgrade:

1. Download an admin backup from `/backup/download`.
2. Verify the backup file exists and can be restored separately.
3. Deploy the new version.
4. Check `/health` and log in.
5. Verify customers, appointments, invoices, payments and inventory.

For future column changes, use an explicit migration tool rather than editing the live database manually. Never run `drop_all()` against a production database.
