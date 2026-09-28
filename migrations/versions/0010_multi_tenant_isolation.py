"""Introduce server-enforced salon tenant isolation.

Revision ID: 0010_multi_tenant_isolation
Revises: 0009_loyalty_rewards
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "0010_multi_tenant_isolation"
down_revision = "0009_loyalty_rewards"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "backup_log",
    "customer",
    "service",
    "staff",
    "appointment",
    "waitlist_entry",
    "expense",
    "inventory_item",
    "invoice",
    "staff_commission",
    "staff_attendance",
    "customer_loyalty",
    "inventory_sale",
    "supplier",
    "inventory_transaction",
    "inventory_purchase",
    "invoice_item",
    "inventory_sale_line",
    "loyalty_transaction",
    "salon_hours",
    "salon_closure",
    "salon_setting",
    "invoice_refund",
    "invoice_payment",
    "staff_schedule",
    "staff_break",
    "salon_package",
    "customer_package",
    "whatsapp_template",
    "gift_card",
    "gift_card_transaction",
    "audit_log",
)


def _create_account_profile_if_missing(bind):
    inspector = inspect(bind)
    if "account_profile" not in inspector.get_table_names():
        op.create_table(
            "account_profile",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("business_name", sa.String(length=150), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", name="uq_account_profile_user"),
            sa.UniqueConstraint("email", name="uq_account_profile_email"),
        )
        return

    columns = {c["name"] for c in inspect(bind).get_columns("account_profile")}
    if "email" not in columns:
        op.add_column("account_profile", sa.Column("email", sa.String(length=320), nullable=True))
    if "created_at" not in columns:
        op.add_column("account_profile", sa.Column("created_at", sa.DateTime(), nullable=True))


def _drop_single_column_unique(bind, table_name, column_name):
    inspector = inspect(bind)
    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("column_names") == [column_name] and constraint.get("name"):
            try:
                op.drop_constraint(constraint["name"], table_name=table_name, type_="unique")
            except Exception:
                pass

    # Some databases represent a UNIQUE constraint as a unique index instead.
    inspector = inspect(bind)
    for index in inspector.get_indexes(table_name):
        if index.get("unique") and index.get("column_names") == [column_name]:
            try:
                op.drop_index(index["name"], table_name=table_name)
            except Exception:
                pass


def _add_account_id(bind, table_name):
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns(table_name)}
    if "account_id" not in columns:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "account_id",
                    sa.Integer(),
                    sa.ForeignKey("account_profile.id"),
                    nullable=True,
                )
            )

    inspector = inspect(bind)
    index_names = {i["name"] for i in inspector.get_indexes(table_name)}
    index_name = f"ix_{table_name}_account_id"
    if index_name not in index_names:
        try:
            op.create_index(index_name, table_name, ["account_id"], unique=False)
        except Exception:
            pass


def _ensure_owner_profile(bind):
    inspector = inspect(bind)
    if "user" not in inspector.get_table_names():
        return None

    # Owners are admin users. Create profiles only for owners so staff accounts
    # continue to inherit the salon from UserStaffLink -> Staff.
    rows = bind.execute(text(
        'SELECT id, username FROM "user" WHERE role = :role ORDER BY id'
    ), {"role": "admin"}).mappings().all()

    if not rows:
        rows = bind.execute(text(
            'SELECT id, username FROM "user" ORDER BY id LIMIT 1'
        )).mappings().all()

    for row in rows:
        existing = bind.execute(
            text("SELECT id FROM account_profile WHERE user_id = :user_id"),
            {"user_id": row["id"]},
        ).scalar()
        if existing is None:
            bind.execute(
                text(
                    "INSERT INTO account_profile (user_id, business_name, email, created_at) "
                    "VALUES (:user_id, :business_name, NULL, CURRENT_TIMESTAMP)"
                ),
                {
                    "user_id": row["id"],
                    "business_name": f'{row["username"]} Salon',
                },
            )

    owner = bind.execute(text(
        'SELECT ap.id FROM account_profile ap '
        'JOIN "user" u ON u.id = ap.user_id '
        'ORDER BY CASE WHEN u.role = :role THEN 0 ELSE 1 END, u.id LIMIT 1'
    ), {"role": "admin"}).scalar()
    return owner


def upgrade():
    bind = op.get_bind()
    _create_account_profile_if_missing(bind)

    for table_name in TENANT_TABLES:
        _add_account_id(bind, table_name)

    # Convert the legacy global uniqueness rules into per-salon rules.
    inspector = inspect(bind)
    if "inventory_item" in inspector.get_table_names():
        _drop_single_column_unique(bind, "inventory_item", "sku")
        try:
            op.create_unique_constraint(
                "uq_inventory_item_account_sku",
                "inventory_item",
                ["account_id", "sku"],
            )
        except Exception:
            pass

    if "salon_hours" in inspector.get_table_names():
        _drop_single_column_unique(bind, "salon_hours", "day_of_week")
        try:
            op.create_unique_constraint(
                "uq_salon_hours_account_day",
                "salon_hours",
                ["account_id", "day_of_week"],
            )
        except Exception:
            pass

    if "salon_closure" in inspector.get_table_names():
        _drop_single_column_unique(bind, "salon_closure", "closure_date")
        try:
            op.create_unique_constraint(
                "uq_salon_closure_account_date",
                "salon_closure",
                ["account_id", "closure_date"],
            )
        except Exception:
            pass

    if "whatsapp_template" in inspector.get_table_names():
        _drop_single_column_unique(bind, "whatsapp_template", "key")
        try:
            op.create_unique_constraint(
                "uq_whatsapp_template_account_key",
                "whatsapp_template",
                ["account_id", "key"],
            )
        except Exception:
            pass

    owner_account_id = _ensure_owner_profile(bind)

    # Existing pre-SaaS rows belong to the original owner account. Nulls remain
    # useful as a fail-closed state for any future background/import paths.
    if owner_account_id is not None:
        for table_name in TENANT_TABLES:
            inspector = inspect(bind)
            if table_name not in inspector.get_table_names():
                continue
            columns = {c["name"] for c in inspector.get_columns(table_name)}
            if "account_id" not in columns:
                continue
            bind.execute(
                text(
                    f'UPDATE "{table_name}" SET account_id = :account_id '
                    'WHERE account_id IS NULL'
                ),
                {"account_id": owner_account_id},
            )

    # No existing data should remain ownerless after migration when a user exists.
    # New application-created rows are assigned automatically by the request guard.


def downgrade():
    raise NotImplementedError(
        "0010_multi_tenant_isolation is intentionally forward-only; "
        "rolling back would re-open cross-tenant data access."
    )
