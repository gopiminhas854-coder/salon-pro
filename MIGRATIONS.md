# Database migrations

Salon Pro uses **Flask-Migrate/Alembic** for production schema changes.

## Current rollout stage

The migration framework is installed and connected to the Flask app. The application still supports its existing `db.create_all()` bootstrap by default so current deployments and tests do not break before the initial migration baseline is captured.

**Do not set `SALON_PRO_AUTO_CREATE_DB=0` on the current production database yet.** The next migration step is to commit the initial schema revision that represents the existing production tables, then switch Render to migration-only startup.

## Development commands

```bash
flask --app app db init
flask --app app db migrate -m "initial schema"
flask --app app db upgrade
```

After the baseline exists, normal schema changes should use:

```bash
flask --app app db migrate -m "describe schema change"
flask --app app db upgrade
```

Before a production upgrade:

1. Download an admin backup from `/backup/download`.
2. Review the migration revision.
3. Deploy.
4. Confirm `flask db upgrade` completes successfully.
5. Check `/health` and verify customers, appointments, invoices, payments and inventory.

Never use `db.drop_all()` against a production database.


### Baseline rollout

The initial revision is `0001_initial_schema`. Render runs `migrate_startup.py` before Gunicorn. It safely stamps an existing pre-Alembic database after verifying the complete baseline table set, then runs `upgrade()` for any later migrations. A partial or unexpected schema fails closed instead of attempting destructive changes.
