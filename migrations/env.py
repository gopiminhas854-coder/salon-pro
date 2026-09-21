"""Alembic environment for Salon Pro."""
from alembic import context
from app import app, db

config = context.config
target_metadata = db.metadata

def run_migrations_offline():
    url = app.config.get("SQLALCHEMY_DATABASE_URI")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    with app.app_context():
        context.configure(connection=db.engine.connect(), target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
