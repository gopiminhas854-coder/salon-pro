"""Enable tenant-aware RLS for the Salon Pro Render database role.

Revision ID: 0012_rls_tenant_isolation
Revises: 0011_colour_lab
"""
from alembic import op

revision = "0012_rls_tenant_isolation"
down_revision = "0011_colour_lab"
branch_labels = None
depends_on = None

TENANT_TABLES = ["backup_log","customer","service","staff","appointment","waitlist_entry","expense","inventory_item","invoice","staff_commission","staff_attendance","customer_loyalty","inventory_sale","supplier","inventory_transaction","inventory_purchase","invoice_item","inventory_sale_line","loyalty_transaction","salon_hours","salon_closure","salon_setting","invoice_refund","invoice_payment","staff_schedule","staff_break","salon_package","customer_package","whatsapp_template","gift_card","gift_card_transaction","audit_log","colour_case","colour_formula_item"]
APP_TABLES = ["backup_log","customer","service","staff","appointment","waitlist_entry","expense","inventory_item","invoice","staff_commission","staff_attendance","customer_loyalty","inventory_sale","supplier","inventory_transaction","inventory_purchase","invoice_item","inventory_sale_line","loyalty_transaction","salon_hours","salon_closure","salon_setting","invoice_refund","invoice_payment","staff_schedule","staff_break","salon_package","customer_package","whatsapp_template","gift_card","gift_card_transaction","audit_log","colour_case","colour_formula_item","user","account_profile","google_identity","subscription","user_staff_link"]

def _tenant_predicate():
    return (
        "(current_setting('salon_pro.maintenance_mode', true) = '1' "
        "OR (current_setting('salon_pro.account_id', true) IS NOT NULL "
        "AND account_id = current_setting('salon_pro.account_id', true)::integer))"
    )

def upgrade():
    for table in APP_TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS "salon_pro_render_access" ON public."{table}"')
        if table in TENANT_TABLES:
            predicate = _tenant_predicate()
        else:
            predicate = "true"
        op.execute(
            f'''CREATE POLICY "salon_pro_render_access" ON public."{table}"
                AS PERMISSIVE FOR ALL TO salon_pro_render
                USING ({predicate}) WITH CHECK ({predicate})'''
        )
        op.execute(f'REVOKE ALL ON public."{table}" FROM anon, authenticated')

def downgrade():
    for table in APP_TABLES:
        op.execute(f'DROP POLICY IF EXISTS "salon_pro_render_access" ON public."{table}"')
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
