# Salon Pro

Salon Pro is a mobile-friendly salon management platform built with Flask, SQLAlchemy and Bootstrap.

## Included

- Dashboard with revenue, expenses, profit and low-stock monitoring
- Customer CRM and customer history
- Appointment booking, calendar and staff conflict detection
- Public online booking
- Service management
- Staff accounts, roles, attendance, performance and commissions
- POS invoices with multiple service/product line items
- Cash, card, UPI and other payment recording
- Configurable tax
- Inventory with stock adjustments and transaction history
- Supplier management and purchase records
- Automatic stock-in on purchases
- Automatic stock-out on product sales
- Exact stock restoration when a linked inventory invoice item is removed
- Customer loyalty points with duplicate-safe transaction references
- Expenses and date-range financial reports
- CSV reporting
- Appointment reminder center with click-to-call
- Salon settings
- Manual database backup
- Production WSGI entry point and Gunicorn configuration
- Health endpoint at /health

## Run locally

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Windows activation:

```text
venv\Scripts\activate
```

Open http://127.0.0.1:5000

## Production

Set a strong `SALON_PRO_SECRET_KEY`. If using HTTPS, set `SESSION_COOKIE_SECURE=1`.

Gunicorn:

```bash
gunicorn wsgi:app
```

The database defaults to SQLite. A `DATABASE_URL` environment variable can be used for a different SQLAlchemy-compatible database.

## Default account

The first database initialization creates:

- Username: `admin`
- Password: `admin123`

**Change this password immediately before real business use.**

## Important deployment note

The application uses `db.create_all()` for additive tables. It does not perform arbitrary schema migrations. Before changing existing columns in a live database, use a proper migration process such as Alembic/Flask-Migrate.

## Public booking

Customers can use:

```text
/book
```

The application prevents overlapping appointments for the selected staff member.

## Health check

```text
/health
```

Returns a small JSON status response for deployment monitoring.


<!-- CI verification trigger -->
