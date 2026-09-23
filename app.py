from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta, timezone
from functools import wraps
import os
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_auth_requests
import secrets
import io
import json
import gzip
import base64
from urllib.parse import quote
from sqlalchemy import func, inspect
from flask_migrate import Migrate

def commit_or_rollback():
    """Commit the current unit of work and always clear failed transactions."""
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


app = Flask(__name__, static_folder='static')
_secret = os.environ.get('SALON_PRO_SECRET_KEY', '')
if os.environ.get('FLASK_ENV') == 'production' and len(_secret) < 32:
    raise RuntimeError('SALON_PRO_SECRET_KEY must be set to a strong 32+ character value in production.')
app.config['SECRET_KEY'] = _secret or 'change-this-secret-key'
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
app.config['TWILIO_ACCOUNT_SID'] = os.environ.get('TWILIO_ACCOUNT_SID', '').strip()
app.config['TWILIO_AUTH_TOKEN'] = os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
app.config['TWILIO_VERIFY_SERVICE_SID'] = os.environ.get('TWILIO_VERIFY_SERVICE_SID', '').strip()
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///salon.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ==================== MODELS ====================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='admin')  # admin / manager / receptionist / staff
    phone_number = db.Column(db.String(20), unique=True)

class BackupLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(180), nullable=False)
    size_bytes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_by = db.relationship('User')

class GoogleIdentity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    google_sub = db.Column(db.String(255), unique=True, nullable=False)
    email = db.Column(db.String(320), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('google_identity', uselist=False))

class UserStaffLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), unique=True, nullable=False)
    user = db.relationship('User', backref=db.backref('staff_link', uselist=False))
    staff = db.relationship('Staff', backref=db.backref('user_link', uselist=False))

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    gender = db.Column(db.String(10))
    address = db.Column(db.Text)
    notes = db.Column(db.Text)
    date_of_birth = db.Column(db.Date)
    anniversary_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointments = db.relationship('Appointment', backref='customer', lazy=True)

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    duration_minutes = db.Column(db.Integer, default=30)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50))  # Hair, Skin, Nails, etc.
    retention_min_days = db.Column(db.Integer, default=30)
    retention_max_days = db.Column(db.Integer, default=45)
    is_active = db.Column(db.Boolean, default=True)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    specialty = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    appointments = db.relationship('Appointment', backref='staff', lazy=True)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.String(10), nullable=False)  # HH:MM
    status = db.Column(db.String(20), default='Scheduled')  # Legacy Scheduled maps to UI Booked; then Confirmed/Arrived/In service/Completed/Cancelled/No-Show
    notes = db.Column(db.Text)
    recurrence_rule = db.Column(db.String(20), default='None')
    recurrence_end_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    service = db.relationship('Service')

class WaitlistEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'), nullable=False)
    preferred_staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'))
    preferred_date = db.Column(db.Date)
    preferred_time = db.Column(db.String(5))
    status = db.Column(db.String(20), default='Open')
    notes = db.Column(db.Text)
    notified_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    customer = db.relationship('Customer', backref='waitlist_entries')
    service = db.relationship('Service')
    preferred_staff = db.relationship('Staff')


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(60), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    expense_date = db.Column(db.Date, default=date.today, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    sku = db.Column(db.String(50), unique=True)
    category = db.Column(db.String(60))
    stock_qty = db.Column(db.Float, default=0)
    reorder_level = db.Column(db.Float, default=5)
    cost_price = db.Column(db.Float, default=0)
    sale_price = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), unique=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    amount = db.Column(db.Float, nullable=False)
    discount = db.Column(db.Float, default=0)
    tax = db.Column(db.Float, default=0)
    tip = db.Column(db.Float, default=0)
    total = db.Column(db.Float, nullable=False)
    payment_status = db.Column(db.String(20), default='Pending')  # Pending, Paid, Partial, Refunded
    commission_rate = db.Column(db.Float, nullable=True)
    payment_method = db.Column(db.String(30))  # Cash, Card, UPI
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointment = db.relationship('Appointment')
    customer = db.relationship('Customer')

class StaffCommission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), unique=True, nullable=False)
    commission_rate = db.Column(db.Float, default=0)
    commission_type = db.Column(db.String(20), default='Percentage')
    staff = db.relationship('Staff', backref=db.backref('commission_settings', uselist=False))

class StaffAttendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='Present')
    check_in = db.Column(db.String(10))
    check_out = db.Column(db.String(10))
    notes = db.Column(db.Text)
    staff = db.relationship('Staff', backref='attendance_records')

class CustomerLoyalty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), unique=True, nullable=False)
    points = db.Column(db.Integer, default=0)
    lifetime_spend = db.Column(db.Float, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    customer = db.relationship('Customer', backref=db.backref('loyalty', uselist=False))

class InventorySale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    invoice = db.relationship('Invoice', backref='inventory_sales')
    inventory_item = db.relationship('InventoryItem')

class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class InventoryTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    transaction_type = db.Column(db.String(30), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, default=0)
    reference = db.Column(db.String(120))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    inventory_item = db.relationship('InventoryItem', backref='inventory_transactions')

class InventoryPurchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    total_cost = db.Column(db.Float, nullable=False)
    purchase_date = db.Column(db.Date, default=date.today, nullable=False)
    reference = db.Column(db.String(120))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    supplier = db.relationship('Supplier', backref='purchases')
    inventory_item = db.relationship('InventoryItem', backref='purchases')

class InventorySaleLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inventory_sale_id = db.Column(db.Integer, db.ForeignKey('inventory_sale.id'), unique=True, nullable=False)
    invoice_item_id = db.Column(db.Integer, db.ForeignKey('invoice_item.id'), unique=True, nullable=False)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    inventory_sale = db.relationship('InventorySale', backref=db.backref('line', uselist=False))
    invoice_item = db.relationship('InvoiceItem', backref=db.backref('inventory_sale_line', uselist=False))
    inventory_item = db.relationship('InventoryItem')

class LoyaltyTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    points = db.Column(db.Integer, nullable=False)
    transaction_type = db.Column(db.String(30), nullable=False)
    reference = db.Column(db.String(120), unique=True)
    amount = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    customer = db.relationship('Customer', backref='loyalty_transactions')

class SalonHours(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.Integer, unique=True, nullable=False)
    open_time = db.Column(db.String(5), default='09:00')
    close_time = db.Column(db.String(5), default='20:00')
    is_closed = db.Column(db.Boolean, default=False)

class SalonClosure(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    closure_date = db.Column(db.Date, unique=True, nullable=False)
    reason = db.Column(db.String(200))

class SalonSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    salon_name = db.Column(db.String(120), default='Salon Pro')
    phone = db.Column(db.String(30))
    address = db.Column(db.Text)
    tax_rate = db.Column(db.Float, default=5)
    loyalty_rate = db.Column(db.Float, default=1)
    reminder_days = db.Column(db.Integer, default=1)
    invoice_prefix = db.Column(db.String(20), default='SP')
    gst_number = db.Column(db.String(30))
    logo_data_url = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class InvoiceRefund(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    refund_method = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    invoice = db.relationship('Invoice', backref='refunds')

class InvoicePayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(30), nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    invoice = db.relationship('Invoice', backref='payments')

class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    description = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Float, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    invoice = db.relationship('Invoice', backref=db.backref('items', lazy=True, cascade='all, delete-orphan'))

class StaffSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.String(5), nullable=False, default='09:00')
    end_time = db.Column(db.String(5), nullable=False, default='20:00')
    is_working = db.Column(db.Boolean, default=True)
    staff = db.relationship('Staff', backref='schedules')

class StaffBreak(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    staff = db.relationship('Staff', backref='breaks')

class SalonPackage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    package_type = db.Column(db.String(20), default='Package')
    description = db.Column(db.Text)
    price = db.Column(db.Float, default=0)
    total_uses = db.Column(db.Integer, default=1)
    validity_days = db.Column(db.Integer, default=30)
    included_services = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CustomerPackage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    package_id = db.Column(db.Integer, db.ForeignKey('salon_package.id'), nullable=False)
    purchased_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.Date, nullable=False)
    uses_total = db.Column(db.Integer, default=1)
    uses_used = db.Column(db.Integer, default=0)
    prepaid_balance = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='Active')
    customer = db.relationship('Customer', backref='customer_packages')
    package = db.relationship('SalonPackage', backref='customer_packages')

class WhatsAppTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class GiftCard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    purchaser_customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    recipient_name = db.Column(db.String(120))
    original_amount = db.Column(db.Float, nullable=False)
    balance = db.Column(db.Float, nullable=False)
    expires_at = db.Column(db.Date)
    status = db.Column(db.String(20), default='Active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    purchaser = db.relationship('Customer', foreign_keys=[purchaser_customer_id])

class GiftCardTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    gift_card_id = db.Column(db.Integer, db.ForeignKey('gift_card.id'), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    gift_card = db.relationship('GiftCard', backref='transactions')
    invoice = db.relationship('Invoice')

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.String(80), nullable=False)
    path = db.Column(db.String(255))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')


# ==================== AUTH ====================

def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    if not user:
        session.clear()
        return None
    link = UserStaffLink.query.filter_by(user_id=user.id).first()
    if link and (not link.staff or not link.staff.is_active):
        session.clear()
        return None
    return user

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue.', 'warning')
            return redirect(url_for('login'))
        role = session.get('role', 'staff')
        if role == 'admin':
            return f(*args, **kwargs)
        if role == 'manager' and request.endpoint not in OWNER_ONLY_ENDPOINTS:
            return f(*args, **kwargs)
        flash('Owner/Admin access is required for this action.', 'danger')
        return redirect(url_for('dashboard'))
    return decorated_function

def get_tax_rate():
    setting = SalonSetting.query.first()
    return max(0, min(100, setting.tax_rate if setting else 5))

def invoice_paid_amount(invoice):
    return round(sum(p.amount for p in InvoicePayment.query.filter_by(invoice_id=invoice.id).all()), 2)

def invoice_refunded_amount(invoice):
    return round(sum(r.amount for r in InvoiceRefund.query.filter_by(invoice_id=invoice.id).all()), 2)

def invoice_net_paid_amount(invoice):
    return round(max(invoice_paid_amount(invoice) - invoice_refunded_amount(invoice), 0), 2)
def invoice_balance(invoice):
    if invoice.payment_status == 'Refunded':
        return 0.0
    return round(max(invoice.total - invoice_net_paid_amount(invoice), 0), 2)

def csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token

def parse_optional_date(value):
    """Parse an optional YYYY-MM-DD form value without crashing the request."""
    value = (value or '').strip()
    if not value:
        return None
    return date.fromisoformat(value)

def upcoming_annual_date(source_date, reference_date=None):
    """Return the next occurrence of a month/day, including leap-day handling."""
    reference_date = reference_date or date.today()
    year = reference_date.year
    try:
        candidate = source_date.replace(year=year)
    except ValueError:
        candidate = date(year, 2, 28)
    if candidate < reference_date:
        try:
            candidate = source_date.replace(year=year + 1)
        except ValueError:
            candidate = date(year + 1, 2, 28)
    return candidate

@app.context_processor
def template_helpers():
    return {'invoice_paid_amount': invoice_paid_amount, 'invoice_refunded_amount': invoice_refunded_amount, 'invoice_net_paid_amount': invoice_net_paid_amount, 'invoice_balance': invoice_balance, 'csrf_token': csrf_token, 'current_user': current_user()}


def recalculate_invoice(invoice):
    subtotal = round(sum(i.total for i in invoice.items), 2)
    invoice.amount = subtotal
    taxable = max(invoice.amount - (invoice.discount or 0), 0)
    invoice.tax = round(taxable * get_tax_rate() / 100, 2)
    invoice.tip = round(max(invoice.tip or 0, 0), 2)
    invoice.total = round(taxable + invoice.tax + invoice.tip, 2)

OWNER_ONLY_ENDPOINTS = {'settings', 'download_backup', 'restore_backup'}

SENSITIVE_READ_ENDPOINTS = {
    'money_center', 'reports', 'export_report_csv', 'insights',
    'staff_performance_overview', 'supplier_intelligence', 'audit_log', 'assistant'
}

ADMIN_ONLY_ENDPOINTS = {
    'settings', 'download_backup',
    'add_staff', 'edit_staff', 'delete_staff',
    'add_service', 'edit_service', 'delete_service',
    'add_expense', 'delete_expense',
    'add_inventory', 'adjust_inventory',
    'update_staff_commission', 'mark_attendance',
    'export_report_csv', 'create_staff_account',
    'reports', 'export_report_csv', 'expenses', 'delete_expense',
    'suppliers', 'add_supplier', 'edit_supplier', 'purchases', 'add_purchase', 'loyalty', 'add_package', 'whatsapp_templates', 'audit_log', 'insights'
}

@app.before_request
def ensure_database():
    # Tests and local development may use the legacy bootstrap path. Production
    # deployments can disable it and rely exclusively on Flask-Migrate.
    if os.environ.get('SALON_PRO_AUTO_CREATE_DB', '1') != '1':
        return None
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table('user'):
            init_db()
        elif not inspector.has_table('google_identity'):
            GoogleIdentity.__table__.create(bind=db.engine, checkfirst=True)
    except Exception as exc:
        app.logger.exception('Database bootstrap failed: %s', exc)
        raise

@app.before_request
def csrf_guard():
    if request.method in {'POST','PUT','PATCH','DELETE'}:
        if request.endpoint == 'google_auth' and request.form.get('credential'):
            return None
        token = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
        if token and secrets.compare_digest(token, session.get('_csrf_token', '')):
            return None
        origin = request.headers.get('Origin') or request.headers.get('Referer')
        if origin and origin.startswith(request.host_url):
            return None
        if app.config.get('TESTING'):
            return None
        return jsonify({'error': 'CSRF validation failed'}), 400

@app.before_request
def enforce_roles():
    user = current_user() if 'user_id' in session else None
    if user:
        # Never trust a stale role stored in the session.
        session['username'] = user.username
        session['role'] = user.role or 'staff'
    if request.endpoint in OWNER_ONLY_ENDPOINTS and user and user.role != 'admin':
        flash('Owner/Admin access is required for this action.', 'danger')
        return redirect(url_for('dashboard'))
    if request.endpoint in ADMIN_ONLY_ENDPOINTS and user and user.role not in {'admin', 'manager'}:
        flash('Manager or Admin access is required for this action.', 'danger')
        return redirect(url_for('dashboard'))
    if request.endpoint in SENSITIVE_READ_ENDPOINTS and user and user.role in {'receptionist', 'staff'}:
        flash('This business information is restricted for your role.', 'danger')
        return redirect(url_for('dashboard'))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user():
            session.clear()
            flash('Please login to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    if request.path.endswith('/sw.js') or response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@app.errorhandler(404)
def handle_not_found(error):
    return (
        "<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Salon Pro - Page not found</title></head><body style=\"font-family:system-ui;padding:40px\">"
        "<h1>Page not found</h1><p>The Salon Pro page you requested does not exist.</p>"
        "<a href=\"/\">Return to Salon Pro</a></body></html>",
        404,
    )


@app.errorhandler(500)
def handle_server_error(error):
    db.session.rollback()
    app.logger.exception("Unhandled Salon Pro request error")
    if request.path.startswith('/api/'):
        return jsonify({
            'error': 'Salon Pro temporarily unavailable.',
            'message': 'The server hit an unexpected error. Please retry.'
        }), 500
    return (
        "<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"theme-color\" content=\"#111214\">"
        "<title>Salon Pro - Temporary error</title></head>"
        "<body style=\"margin:0;background:#f7f5f0;color:#171717;font-family:system-ui,-apple-system,sans-serif\">"
        "<main style=\"max-width:620px;margin:0 auto;padding:12vh 24px\">"
        "<div style=\"background:#fff;border:1px solid #e9e6df;border-radius:20px;padding:32px;box-shadow:0 10px 40px rgba(0,0,0,.06)\">"
        "<div style=\"font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#8a806f;font-weight:700\">Salon Pro</div>"
        "<h1 style=\"font-size:30px;margin:10px 0 8px\">Something went wrong</h1>"
        "<p style=\"color:#6f6a62;line-height:1.6\">The server hit an unexpected error. Your saved data was not intentionally changed by this error.</p>"
        "<div style=\"display:flex;gap:10px;flex-wrap:wrap;margin-top:22px\">"
        "<a href=\"javascript:location.reload()\" style=\"display:inline-block;background:#171717;color:#fff;text-decoration:none;padding:12px 16px;border-radius:10px;font-weight:700\">Try again</a>"
        "<a href=\"/\" style=\"display:inline-block;border:1px solid #ddd8cf;color:#171717;text-decoration:none;padding:12px 16px;border-radius:10px;font-weight:700\">Dashboard</a>"
        "<a href=\"/health\" style=\"display:inline-block;border:1px solid #ddd8cf;color:#171717;text-decoration:none;padding:12px 16px;border-radius:10px;font-weight:700\">Check health</a>"
        "</div></div></main></body></html>"
    ), 500


@app.route('/health')
def health():
    # Health must verify database connectivity; otherwise Render can report
    # a healthy web process while the application database is unavailable.
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify({'status': 'ok', 'service': 'Salon Pro', 'database': 'ok'}), 200
    except Exception:
        db.session.rollback()
        return jsonify({'status': 'degraded', 'service': 'Salon Pro', 'database': 'unavailable'}), 503

def establish_login_session(user):
    session.clear()
    session['user_id'] = user.id
    session['username'] = user.username
    session['role'] = user.role or 'staff'


@app.route('/auth/google', methods=['POST'])
def google_auth():
    """Verify a Google ID token and link/sign in the matching Salon Pro account."""
    destination = url_for('settings') if session.get('user_id') else url_for('login')
    if not app.config.get('GOOGLE_CLIENT_ID'):
        flash('Google Sign-In is not configured yet. Set GOOGLE_CLIENT_ID on the server.', 'warning')
        return redirect(destination)

    credential = request.form.get('credential', '').strip()
    if not credential:
        flash('Google Sign-In did not return a credential.', 'danger')
        return redirect(destination)

    try:
        claims = google_id_token.verify_oauth2_token(
            credential,
            google_auth_requests.Request(),
            app.config['GOOGLE_CLIENT_ID']
        )
    except Exception:
        app.logger.exception('Google ID token verification failed')
        flash('Google Sign-In could not be verified. Please try again.', 'danger')
        return redirect(destination)

    google_sub = str(claims.get('sub') or '').strip()
    email = str(claims.get('email') or '').strip().lower()
    if not google_sub or not email or claims.get('email_verified') is not True:
        flash('Google did not provide a verified account identity.', 'danger')
        return redirect(destination)

    identity = GoogleIdentity.query.filter_by(google_sub=google_sub).first()
    current = current_user() if session.get('user_id') else None

    if current:
        existing_for_user = GoogleIdentity.query.filter_by(user_id=current.id).first()
        if identity and identity.user_id != current.id:
            flash('That Google account is already connected to another Salon Pro account.', 'danger')
            return redirect(url_for('settings'))
        if existing_for_user and existing_for_user.google_sub != google_sub:
            flash('This Salon Pro account already has a different Google account connected.', 'warning')
            return redirect(url_for('settings'))
        if not identity:
            identity = GoogleIdentity(user_id=current.id, google_sub=google_sub, email=email)
            db.session.add(identity)
        else:
            identity.email = email
        db.session.commit()
        flash('Google account connected successfully. You can now use Continue with Google at login.', 'success')
        return redirect(url_for('settings'))

    if not identity:
        flash('This Google account is not connected yet. Log in normally first, then open Settings → Google Sign-In → Connect Google.', 'warning')
        return redirect(url_for('login'))

    user = db.session.get(User, identity.user_id)
    if not user:
        db.session.delete(identity)
        db.session.commit()
        flash('The linked Salon Pro account no longer exists.', 'danger')
        return redirect(url_for('login'))

    link = UserStaffLink.query.filter_by(user_id=user.id).first()
    if link and (not link.staff or not link.staff.is_active):
        flash('This Salon Pro account is inactive.', 'danger')
        return redirect(url_for('login'))

    establish_login_session(user)
    flash('Welcome back!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        link = UserStaffLink.query.filter_by(user_id=user.id).first() if user else None
        if user and (not link or (link.staff and link.staff.is_active)) and check_password_hash(user.password_hash, password):
            establish_login_session(user)
            flash('Welcome back!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

def normalize_phone_number(value):
    """Normalize Indian +91 phone numbers for OTP authentication."""
    raw = (value or '').strip().replace(' ', '').replace('-', '')
    if raw.startswith('0'):
        raw = '+91' + raw[1:]
    elif raw.isdigit() and len(raw) == 10:
        raw = '+91' + raw
    if not raw.startswith('+') or not raw[1:].isdigit() or len(raw) < 10:
        return None
    return raw


def twilio_verify_configured():
    return all((
        app.config.get('TWILIO_ACCOUNT_SID'),
        app.config.get('TWILIO_AUTH_TOKEN'),
        app.config.get('TWILIO_VERIFY_SERVICE_SID'),
    ))


def twilio_verify_request(path, data):
    if not twilio_verify_configured():
        raise RuntimeError('Phone OTP is not configured on the server.')
    import requests
    url = f"https://verify.twilio.com/v2/Services/{app.config['TWILIO_VERIFY_SERVICE_SID']}/{path}"
    response = requests.post(
        url,
        data=data,
        auth=(app.config['TWILIO_ACCOUNT_SID'], app.config['TWILIO_AUTH_TOKEN']),
        timeout=15,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok:
        raise RuntimeError(payload.get('message') or 'Phone verification service request failed.')
    return payload


@app.route('/auth/phone/send', methods=['POST'])
def phone_send_otp():
    phone = normalize_phone_number(request.form.get('phone'))
    if not phone:
        flash('Enter a valid phone number, for example +91 98765 43210.', 'danger')
        return redirect(url_for('login'))
    if not twilio_verify_configured():
        flash('Phone login is not configured yet. Add the Twilio Verify settings on the server.', 'warning')
        return redirect(url_for('login'))
    try:
        twilio_verify_request('Verifications', {'To': phone, 'Channel': 'sms'})
        session['phone_login_number'] = phone
        flash('OTP sent to your phone.', 'success')
        return redirect(url_for('phone_login'))
    except Exception as exc:
        app.logger.exception('Phone OTP send failed: %s', exc)
        flash('Could not send the OTP. Please try again.', 'danger')
        return redirect(url_for('login'))


@app.route('/auth/phone', methods=['GET', 'POST'])
def phone_login():
    phone = session.get('phone_login_number')
    if not phone:
        return redirect(url_for('login'))
    if request.method == 'POST':
        code = (request.form.get('code') or '').strip()
        if not code.isdigit() or len(code) < 4 or len(code) > 8:
            flash('Enter the OTP sent to your phone.', 'danger')
            return render_template('phone_login.html', phone=phone)
        try:
            result = twilio_verify_request('VerificationCheck', {'To': phone, 'Code': code})
            if result.get('status') != 'approved':
                flash('Invalid or expired OTP.', 'danger')
                return render_template('phone_login.html', phone=phone)
            user = User.query.filter_by(phone_number=phone).first()
            if not user:
                flash('This phone number is not linked to a Salon Pro account. Log in with your password and link it in Settings first.', 'warning')
                return redirect(url_for('login'))
            link = UserStaffLink.query.filter_by(user_id=user.id).first()
            if link and (not link.staff or not link.staff.is_active):
                flash('This Salon Pro account is inactive.', 'danger')
                return redirect(url_for('login'))
            establish_login_session(user)
            flash('Welcome back!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as exc:
            app.logger.exception('Phone OTP verification failed: %s', exc)
            flash('Could not verify the OTP. Please try again.', 'danger')
    return render_template('phone_login.html', phone=phone)


@app.route('/account/phone/send', methods=['POST'])
@login_required
def phone_link_send():
    phone = normalize_phone_number(request.form.get('phone'))
    if not phone:
        flash('Enter a valid phone number, for example +91 98765 43210.', 'danger')
        return redirect(url_for('settings'))
    existing = User.query.filter(User.phone_number == phone, User.id != session['user_id']).first()
    if existing:
        flash('That phone number is already linked to another Salon Pro account.', 'danger')
        return redirect(url_for('settings'))
    if not twilio_verify_configured():
        flash('Phone login is not configured yet. Add the Twilio Verify settings on the server.', 'warning')
        return redirect(url_for('settings'))
    try:
        twilio_verify_request('Verifications', {'To': phone, 'Channel': 'sms'})
        session['phone_link_number'] = phone
        flash('OTP sent. Enter it below to link your phone.', 'success')
    except Exception as exc:
        app.logger.exception('Phone link OTP send failed: %s', exc)
        flash('Could not send the OTP. Please try again.', 'danger')
    return redirect(url_for('settings'))


@app.route('/account/phone/verify', methods=['POST'])
@login_required
def phone_link_verify():
    phone = session.get('phone_link_number')
    code = (request.form.get('code') or '').strip()
    if not phone:
        flash('Start phone linking first.', 'warning')
        return redirect(url_for('settings'))
    try:
        result = twilio_verify_request('VerificationCheck', {'To': phone, 'Code': code})
        if result.get('status') != 'approved':
            flash('Invalid or expired OTP.', 'danger')
            return redirect(url_for('settings'))
        user = User.query.get_or_404(session['user_id'])
        existing = User.query.filter(User.phone_number == phone, User.id != user.id).first()
        if existing:
            flash('That phone number is already linked to another Salon Pro account.', 'danger')
            return redirect(url_for('settings'))
        user.phone_number = phone
        db.session.commit()
        session.pop('phone_link_number', None)
        flash('Phone number linked successfully. You can now log in with OTP.', 'success')
    except Exception as exc:
        db.session.rollback()
        app.logger.exception('Phone link verification failed: %s', exc)
        flash('Could not verify the OTP. Please try again.', 'danger')
    return redirect(url_for('settings'))


@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))


def record_inventory_transaction(item, transaction_type, quantity, unit_cost=0, reference=None, notes=None):
    tx = InventoryTransaction(
        inventory_item_id=item.id,
        transaction_type=transaction_type,
        quantity=quantity,
        unit_cost=unit_cost or 0,
        reference=reference,
        notes=notes,
        created_by=session.get('user_id')
    )
    db.session.add(tx)
    return tx

def award_loyalty_for_invoice(invoice):
    if invoice.payment_status != 'Paid' or not invoice.customer_id:
        return
    reference = f'invoice:{invoice.id}'
    if LoyaltyTransaction.query.filter_by(reference=reference).first():
        return
    setting = SalonSetting.query.first()
    rate = setting.loyalty_rate if setting else 1
    points = max(0, int(round(max(invoice.total, 0) * rate / 100)))
    loyalty = CustomerLoyalty.query.filter_by(customer_id=invoice.customer_id).first()
    if not loyalty:
        loyalty = CustomerLoyalty(customer_id=invoice.customer_id, points=0, lifetime_spend=0)
        db.session.add(loyalty)
    loyalty.points += points
    loyalty.lifetime_spend += max(invoice.total, 0)
    loyalty.updated_at = datetime.utcnow()
    db.session.add(LoyaltyTransaction(customer_id=invoice.customer_id, points=points,
                                       transaction_type='Earn', reference=reference,
                                       amount=max(invoice.total, 0)))

APPOINTMENT_STATUSES = ['Booked', 'Confirmed', 'Arrived', 'In service', 'Completed', 'Cancelled', 'No-Show']
ACTIVE_APPOINTMENT_STATUSES = {'Scheduled', 'Booked', 'Confirmed', 'Arrived', 'In service'}

def normalize_appointment_status(status):
    return 'Booked' if status == 'Scheduled' else (status or 'Booked')

def booking_allowed(appointment_date, appointment_time, duration_minutes):
    if appointment_date < date.today():
        return False, 'Appointments cannot be booked for a past date.'
    closure = SalonClosure.query.filter_by(closure_date=appointment_date).first()
    if closure:
        return False, closure.reason or 'The salon is closed on this date.'
    hours = SalonHours.query.filter_by(day_of_week=appointment_date.weekday()).first()
    if hours and hours.is_closed:
        return False, 'The salon is closed on this day.'
    if hours:
        try:
            start = datetime.strptime(appointment_time, '%H:%M').time()
            opening = datetime.strptime(hours.open_time, '%H:%M').time()
            closing = datetime.strptime(hours.close_time, '%H:%M').time()
            end = datetime.combine(appointment_date, start) + timedelta(minutes=duration_minutes or 30)
            if start < opening or end.time() > closing or end.date() != appointment_date:
                return False, f'Bookings are available from {hours.open_time} to {hours.close_time}.'
        except ValueError:
            return False, 'Please choose a valid appointment time.'
    return True, ''

def appointment_conflict(staff_id, appointment_date, appointment_time, duration_minutes, exclude_id=None):
    schedule = StaffSchedule.query.filter_by(staff_id=staff_id, day_of_week=appointment_date.weekday()).first()
    if schedule and not schedule.is_working:
        return 'This staff member is not available on this day.'
    if schedule:
        start_time = datetime.strptime(appointment_time, '%H:%M').time()
        start_limit = datetime.strptime(schedule.start_time, '%H:%M').time()
        end_limit = datetime.strptime(schedule.end_time, '%H:%M').time()
        end_candidate = datetime.combine(appointment_date, start_time) + timedelta(minutes=duration_minutes or 30)
        if start_time < start_limit or end_candidate.time() > end_limit or end_candidate.date() != appointment_date:
            return f'Staff availability is {schedule.start_time}–{schedule.end_time}.'
    start = datetime.combine(appointment_date, datetime.strptime(appointment_time, '%H:%M').time())
    end = start + timedelta(minutes=duration_minutes or 30)
    breaks = StaffBreak.query.filter_by(
        staff_id=staff_id, day_of_week=appointment_date.weekday(), is_active=True
    ).all()
    for break_row in breaks:
        break_start = datetime.combine(appointment_date, datetime.strptime(break_row.start_time, '%H:%M').time())
        break_end = datetime.combine(appointment_date, datetime.strptime(break_row.end_time, '%H:%M').time())
        if start < break_end and break_start < end:
            return f'Staff break is from {break_row.start_time} to {break_row.end_time}.'
    query = Appointment.query.filter(
        Appointment.staff_id == staff_id,
        Appointment.appointment_date == appointment_date,
        Appointment.status.in_(list(ACTIVE_APPOINTMENT_STATUSES))
    )
    if exclude_id:
        query = query.filter(Appointment.id != exclude_id)
    for existing in query.all():
        existing_start = datetime.combine(
            appointment_date, datetime.strptime(existing.appointment_time, '%H:%M').time()
        )
        existing_end = existing_start + timedelta(minutes=existing.service.duration_minutes or 30)
        if start < existing_end and existing_start < end:
            return f'Staff member is already booked from {existing.appointment_time}.'
    return None

def smart_schedule_slots(service_id, target_date, preferred_staff_id=None, limit=8):
    service = Service.query.filter_by(id=service_id, is_active=True).first_or_404()
    staff_rows = []
    if preferred_staff_id:
        preferred = Staff.query.filter_by(id=preferred_staff_id, is_active=True).first()
        if preferred:
            staff_rows.append(preferred)
    for member in Staff.query.filter_by(is_active=True).order_by(Staff.name).all():
        if all(member.id != row.id for row in staff_rows):
            staff_rows.append(member)

    hours = SalonHours.query.filter_by(day_of_week=target_date.weekday()).first()
    if hours and hours.is_closed:
        return []
    opening = datetime.strptime(hours.open_time, '%H:%M').time() if hours else datetime.strptime('09:00', '%H:%M').time()
    closing = datetime.strptime(hours.close_time, '%H:%M').time() if hours else datetime.strptime('20:00', '%H:%M').time()
    slots = []
    now = datetime.now()
    for member in staff_rows:
        schedule = StaffSchedule.query.filter_by(staff_id=member.id, day_of_week=target_date.weekday()).first()
        if schedule and not schedule.is_working:
            continue
        start = datetime.strptime(schedule.start_time, '%H:%M').time() if schedule else opening
        end = datetime.strptime(schedule.end_time, '%H:%M').time() if schedule else closing
        start_dt = max(datetime.combine(target_date, opening), datetime.combine(target_date, start))
        end_dt = min(datetime.combine(target_date, closing), datetime.combine(target_date, end))
        cursor = start_dt
        while cursor + timedelta(minutes=service.duration_minutes or 30) <= end_dt:
            if target_date > date.today() or cursor >= now:
                hhmm = cursor.strftime('%H:%M')
                allowed, _ = booking_allowed(target_date, hhmm, service.duration_minutes or 30)
                conflict = appointment_conflict(member.id, target_date, hhmm, service.duration_minutes or 30) if allowed else 'blocked'
                if allowed and not conflict:
                    slots.append({'date': target_date.isoformat(), 'time': hhmm, 'staff_id': member.id, 'staff_name': member.name, 'service_id': service.id, 'service_name': service.name})
                    if len(slots) >= limit:
                        return slots
            cursor += timedelta(minutes=15)
    return slots


# ==================== CALENDAR / BOOKING ====================

@app.route('/calendar')
@login_required
def calendar_view():
    selected_text=request.args.get('date',date.today().isoformat())
    view=request.args.get('view','week').lower()
    if view not in {'day','week','month'}: view='week'
    try:
        selected=datetime.strptime(selected_text,'%Y-%m-%d').date()
    except ValueError:
        selected=date.today(); selected_text=selected.isoformat()
    if view=='day':
        days=[selected]; previous_date=selected-timedelta(days=1); next_date=selected+timedelta(days=1)
    elif view=='month':
        month_start=selected.replace(day=1)
        next_month=(month_start+timedelta(days=32)).replace(day=1)
        grid_start=month_start-timedelta(days=month_start.weekday())
        grid_end=next_month-timedelta(days=1)
        grid_end += timedelta(days=6-grid_end.weekday())
        days=[]; d=grid_start
        while d<=grid_end:
            days.append(d); d+=timedelta(days=1)
        previous_date=(month_start-timedelta(days=1)).replace(day=1); next_date=next_month
    else:
        week_start=selected-timedelta(days=selected.weekday())
        days=[week_start+timedelta(days=i) for i in range(7)]
        previous_date=selected-timedelta(days=7); next_date=selected+timedelta(days=7)
    appointments_by_day={d:Appointment.query.filter_by(appointment_date=d).order_by(Appointment.appointment_time).all() for d in days}
    return render_template('calendar.html',selected=selected,selected_text=selected_text,days=days,
        appointments_by_day=appointments_by_day,previous_date=previous_date.isoformat(),next_date=next_date.isoformat(),
        today_iso=date.today().isoformat(),view=view,month_label=selected.strftime('%B %Y'))

@app.route('/appointments/move',methods=['POST'])
@login_required
def move_appointment():
    appt=Appointment.query.get_or_404(request.form.get('appointment_id',type=int))
    try:
        new_date=datetime.strptime(request.form['appointment_date'],'%Y-%m-%d').date()
        new_time=request.form.get('appointment_time',appt.appointment_time)
        allowed,reason=booking_allowed(new_date,new_time,appt.service.duration_minutes or 30)
        if not allowed: return jsonify({'ok':False,'error':reason}),400
        conflict=appointment_conflict(appt.staff_id,new_date,new_time,appt.service.duration_minutes or 30,exclude_id=appt.id)
        if conflict: return jsonify({'ok':False,'error':conflict}),409
        appt.appointment_date=new_date; appt.appointment_time=new_time; db.session.commit()
        return jsonify({'ok':True,'date':new_date.isoformat(),'time':new_time})
    except (KeyError,ValueError,TypeError):
        db.session.rollback(); return jsonify({'ok':False,'error':'Invalid appointment move.'}),400

@app.route('/book', methods=['GET', 'POST'])
def public_booking():
    if request.method == 'POST':
        try:
            name = request.form['name'].strip()
            phone = request.form['phone'].strip()
            service_id = int(request.form['service_id'])
            staff_id = int(request.form['staff_id'])
            appointment_date = datetime.strptime(request.form['appointment_date'], '%Y-%m-%d').date()
            appointment_time = request.form['appointment_time']
            if not name or not phone:
                raise ValueError
            service = Service.query.filter_by(id=service_id, is_active=True).first_or_404()
            staff = Staff.query.filter_by(id=staff_id, is_active=True).with_for_update().first_or_404()
            allowed, reason = booking_allowed(appointment_date, appointment_time, service.duration_minutes or 30)
            if not allowed:
                flash(reason, 'danger')
                return redirect(url_for('public_booking'))
            start = datetime.combine(appointment_date, datetime.strptime(appointment_time, '%H:%M').time())
            end = start + timedelta(minutes=service.duration_minutes or 30)
            conflict = appointment_conflict(staff_id, appointment_date, appointment_time, service.duration_minutes or 30)
            if conflict:
                flash(conflict, 'danger')
                return redirect(url_for('public_booking'))
            customer = Customer.query.filter_by(phone=phone).first()
            if not customer:
                customer = Customer(name=name, phone=phone)
                db.session.add(customer)
                db.session.flush()
            else:
                customer.name = name
            db.session.add(Appointment(customer_id=customer.id, staff_id=staff_id, service_id=service_id,
                                        appointment_date=appointment_date, appointment_time=appointment_time,
                                        status='Scheduled', notes='Online booking'))
            db.session.commit()
            flash('Booking confirmed! The salon will see your appointment in the calendar.', 'success')
            return redirect(url_for('public_booking'))
        except (KeyError, ValueError, TypeError):
            flash('Please enter valid booking details.', 'danger')
    customers = Customer.query.order_by(Customer.name).all()
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    staff_list = Staff.query.filter_by(is_active=True).order_by(Staff.name).all()
    return render_template('booking.html', services=services, staff_list=staff_list, today_iso=date.today().isoformat())

def _backup_json():
    tables = {}
    for table in db.metadata.sorted_tables:
        rows = []
        for row in db.session.execute(table.select()).mappings():
            item = {}
            for key, value in row.items():
                if isinstance(value, (datetime, date)):
                    item[key] = value.isoformat()
                else:
                    item[key] = value
            rows.append(item)
        tables[table.name] = rows
    return {
        'format': 'salon-pro-backup',
        'version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'database': db.engine.url.get_backend_name(),
        'tables': tables,
    }

def _restore_value(column, value):
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        return value
    if python_type is date:
        return date.fromisoformat(value)
    if python_type is datetime:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
    if python_type is bool and isinstance(value, str):
        return value.lower() in {'1', 'true', 'yes', 'on'}
    return value

@app.route('/backup-center')
@login_required
def backup_center():
    if session.get('role') not in {'admin'}:
        flash('Owner/Admin access is required for backups.', 'danger')
        return redirect(url_for('dashboard'))
    logs = BackupLog.query.order_by(BackupLog.created_at.desc()).limit(20).all()
    last = logs[0] if logs else None
    return render_template('backup_center.html', logs=logs, last=last)

@app.route('/backup/download')
@admin_required
def download_backup():
    payload = json.dumps(_backup_json(), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    compressed = gzip.compress(payload, compresslevel=6)
    db.session.add(BackupLog(file_name=f"salon-pro-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}Z.json.gz", size_bytes=len(compressed), created_by_user_id=session.get('user_id')))
    db.session.commit()
    return send_file(
        io.BytesIO(compressed),
        mimetype='application/gzip',
        as_attachment=True,
        download_name=f"salon-pro-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}Z.json.gz"
    )

@app.route('/backup/restore', methods=['POST'])
@admin_required
def restore_backup():
    upload = request.files.get('backup_file')
    confirmation = (request.form.get('restore_confirmation') or '').strip().upper()
    if not upload or not upload.filename:
        flash('Choose a Salon Pro backup file first.', 'danger')
        return redirect(url_for('settings'))
    if confirmation != 'RESTORE':
        flash('Type RESTORE to confirm replacing the current database data.', 'danger')
        return redirect(url_for('settings'))
    try:
        raw = upload.read()
        if upload.filename.lower().endswith(('.gz', '.gzip')):
            raw = gzip.decompress(raw)
        backup = json.loads(raw.decode('utf-8'))
        if backup.get('format') != 'salon-pro-backup' or backup.get('version') != 1:
            raise ValueError('Unsupported backup format.')
        tables = backup.get('tables')
        if not isinstance(tables, dict):
            raise ValueError('Backup table data is invalid.')

        known = set(db.metadata.tables)
        unknown = set(tables) - known
        missing_tables = known - set(tables)
        if unknown:
            raise ValueError(f'Backup contains unknown tables: {", ".join(sorted(unknown))}')
        if missing_tables:
            raise ValueError(f'Backup is incomplete; missing tables: {", ".join(sorted(missing_tables))}')
        for table_name, rows in tables.items():
            table = db.metadata.tables[table_name]
            expected_columns = {col.name for col in table.columns}
            if not isinstance(rows, list):
                raise ValueError(f'Backup rows for {table_name} must be a list.')
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f'Invalid row in {table_name}.')
                if set(row) != expected_columns:
                    raise ValueError(f'Backup schema mismatch for {table_name}. Expected columns: {", ".join(sorted(expected_columns))}')

        db.session.rollback()
        # Delete children before parents so foreign keys remain valid.
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        # Restore in dependency order.
        for table in db.metadata.sorted_tables:
            rows = tables.get(table.name, [])
            if not rows:
                continue
            valid_columns = {c.name: c for c in table.columns}
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f'Invalid row in {table.name}.')
                values = {key: _restore_value(valid_columns[key], value)
                          for key, value in row.items() if key in valid_columns}
                db.session.execute(table.insert().values(**values))

        # PostgreSQL integer sequences must be moved past restored primary keys.
        if db.engine.dialect.name == 'postgresql':
            for table in db.metadata.sorted_tables:
                pk = next(iter(table.primary_key.columns), None)
                if pk is not None and getattr(pk.type, 'python_type', None) is int:
                    db.session.execute(db.text(
                        "SELECT setval(pg_get_serial_sequence(:table_name, :column_name), "
                        "COALESCE((SELECT MAX(" + pk.name + ") FROM " + table.name + "), 1), true)"
                    ), {'table_name': table.name, 'column_name': pk.name})
        db.session.commit()
        flash('Database restore completed successfully.', 'success')
    except Exception as exc:
        db.session.rollback()
        app.logger.exception('Database restore failed: %s', exc)
        flash(f'Database restore failed: {exc}', 'danger')
    return redirect(url_for('settings'))

# ==================== DASHBOARD ====================

@app.route('/')
@login_required
def dashboard():
    today = date.today()
    now_text = datetime.now().strftime('%H:%M')
    today_appointments = Appointment.query.filter_by(appointment_date=today).order_by(Appointment.appointment_time).all()
    total_customers = Customer.query.count()
    total_staff = Staff.query.filter_by(is_active=True).count()
    total_services = Service.query.filter_by(is_active=True).count()
    month_start = today.replace(day=1)
    prev_end = month_start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    month_invoices = Invoice.query.filter(Invoice.created_at >= datetime.combine(month_start,datetime.min.time())).all()
    prev_invoices = Invoice.query.filter(Invoice.created_at >= datetime.combine(prev_start,datetime.min.time()),Invoice.created_at < datetime.combine(month_start,datetime.min.time())).all()
    monthly_revenue = round(sum(invoice_net_paid_amount(i) for i in month_invoices),2)
    previous_month_revenue = round(sum(invoice_net_paid_amount(i) for i in prev_invoices),2)
    monthly_expenses = round(sum(e.amount for e in Expense.query.filter(Expense.expense_date>=month_start,Expense.expense_date<=today).all()),2)
    monthly_profit = round(monthly_revenue-monthly_expenses,2)
    monthly_growth = round((monthly_revenue-previous_month_revenue)/previous_month_revenue*100,1) if previous_month_revenue else None
    week_start = today-timedelta(days=6)
    weekly_invoices = Invoice.query.filter(func.date(Invoice.created_at)>=week_start,func.date(Invoice.created_at)<=today).all()
    weekly_revenue = round(sum(invoice_net_paid_amount(i) for i in weekly_invoices),2)
    weekly_expenses = round(sum(e.amount for e in Expense.query.filter(Expense.expense_date>=week_start,Expense.expense_date<=today).all()),2)
    weekly_profit = round(weekly_revenue-weekly_expenses,2)
    today_invoices = Invoice.query.filter(func.date(Invoice.created_at)==today).all()
    today_revenue = round(sum(invoice_net_paid_amount(i) for i in today_invoices),2)
    today_expenses = round(sum(e.amount for e in Expense.query.filter_by(expense_date=today).all()),2)
    today_profit = round(today_revenue-today_expenses,2)
    pending = Invoice.query.filter(Invoice.payment_status.in_(['Pending','Partial'])).all()
    outstanding_amount = round(sum(invoice_balance(i) for i in pending),2)
    completed_today = Appointment.query.filter_by(appointment_date=today,status='Completed').count()
    low_stock = InventoryItem.query.filter(InventoryItem.is_active==True,InventoryItem.stock_qty<=InventoryItem.reorder_level).all()
    potential_inventory_profit = round(sum(max((i.sale_price or 0)-(i.cost_price or 0),0)*max(i.stock_qty or 0,0) for i in InventoryItem.query.filter_by(is_active=True).all()),2)
    next_customers = [a for a in today_appointments if a.status in ACTIVE_APPOINTMENT_STATUSES and a.appointment_time >= now_text][:6] or [a for a in today_appointments if a.status in ACTIVE_APPOINTMENT_STATUSES][:6]
    working_staff = Staff.query.filter_by(is_active=True).join(StaffAttendance, StaffAttendance.staff_id == Staff.id).filter(
        StaffAttendance.attendance_date==today, StaffAttendance.status=='Present',
        StaffAttendance.check_in.isnot(None),
        db.or_(StaffAttendance.check_out.is_(None), StaffAttendance.check_out=='')
    ).all()
    birthday_today, anniversary_today = [], []
    for customer in Customer.query.all():
        if customer.date_of_birth and (customer.date_of_birth.month,customer.date_of_birth.day)==(today.month,today.day):
            birthday_today.append(customer)
        if customer.anniversary_date and (customer.anniversary_date.month,customer.anniversary_date.day)==(today.month,today.day):
            anniversary_today.append(customer)
    retention_due, retention_at_risk = [], []
    for customer in Customer.query.all():
        metrics = _customer_metrics(customer.id)
        if metrics['visits'] and metrics['days_since_visit'] is not None:
            service = metrics['last_visit'].service if metrics['last_visit'] else None
            low, high = service_retention_window(service, metrics['avg_visit_interval_days'])
            if metrics['days_since_visit'] >= high:
                retention_at_risk.append((customer,metrics))
            elif metrics['days_since_visit'] >= low:
                retention_due.append((customer,metrics))
    confirmed_today = Appointment.query.filter_by(appointment_date=today,status='Confirmed').count()
    ai_priority = []
    if retention_at_risk: ai_priority.append({'tone':'danger','icon':'🔴','text':f'{len(retention_at_risk)} customers are overdue for a return'})
    if low_stock: ai_priority.append({'tone':'warning','icon':'🟠','text':f'{len(low_stock)} products need reordering'})
    if confirmed_today: ai_priority.append({'tone':'success','icon':'🟢','text':f'{confirmed_today} appointments confirmed today'})
    ai_priority.append({'tone':'dark','icon':'💰','text':f'₹{today_revenue:,.0f} collected today'})
    if outstanding_amount: ai_priority.append({'tone':'warning','icon':'💳','text':f'₹{outstanding_amount:,.0f} is still to collect'})
    upcoming = Appointment.query.filter(
        Appointment.appointment_date>today, Appointment.appointment_date<=today+timedelta(days=7),
        Appointment.status.in_(list(ACTIVE_APPOINTMENT_STATUSES))
    ).order_by(Appointment.appointment_date,Appointment.appointment_time).limit(6).all()
    service_counts = {}
    for a in Appointment.query.filter(Appointment.appointment_date>=month_start,Appointment.appointment_date<=today,Appointment.status=='Completed').all():
        if a.service: service_counts[a.service.name] = service_counts.get(a.service.name,0)+1
    top_services = sorted(service_counts.items(),key=lambda x:(-x[1],x[0]))[:5]
    return render_template('dashboard.html',
        today_appointments=today_appointments,total_customers=total_customers,total_staff=total_staff,total_services=total_services,
        monthly_revenue=monthly_revenue,previous_month_revenue=previous_month_revenue,monthly_growth=monthly_growth,monthly_expenses=monthly_expenses,monthly_profit=monthly_profit,
        weekly_revenue=weekly_revenue,weekly_expenses=weekly_expenses,weekly_profit=weekly_profit,
        outstanding_amount=outstanding_amount,pending_invoices=len(pending),pending_invoice_rows=pending[:8],
        today=today,today_revenue=today_revenue,today_expenses=today_expenses,today_profit=today_profit,completed_today=completed_today,
        low_stock_count=len(low_stock),low_stock_items=low_stock[:5],potential_inventory_profit=potential_inventory_profit,
        upcoming=upcoming,top_services=top_services,next_customers=next_customers,working_staff=working_staff,
        birthday_today=birthday_today,anniversary_today=anniversary_today,retention_due=retention_due[:8],retention_at_risk=retention_at_risk[:8],
        ai_priority=ai_priority[:6])
@app.route('/payments')
@login_required
def payments():
    outstanding = [
        invoice for invoice in Invoice.query.filter(Invoice.payment_status.in_(['Pending','Partial']))
        .order_by(Invoice.created_at.asc()).all()
        if invoice_balance(invoice) > 0
    ]
    return render_template('payments.html', invoices=outstanding[:100])

@app.route('/money-center')
@login_required
def money_center():
    today=date.today(); month_start=today.replace(day=1); week_start=today-timedelta(days=6); prev_end=month_start-timedelta(days=1); prev_start=prev_end.replace(day=1)
    def data(start,end):
        invs=Invoice.query.filter(func.date(Invoice.created_at)>=start,func.date(Invoice.created_at)<=end).all()
        exps=Expense.query.filter(Expense.expense_date>=start,Expense.expense_date<=end).all()
        rev=round(sum(invoice_net_paid_amount(i) for i in invs),2); exp=round(sum(e.amount for e in exps),2); paid=[i for i in invs if invoice_net_paid_amount(i)>0]
        return {'revenue':rev,'expenses':exp,'profit':round(rev-exp,2),'customers':len({i.customer_id for i in paid if i.customer_id}),'average_bill':round(rev/len(paid),2) if paid else 0}
    today_data=data(today,today); week_data=data(week_start,today); month_data=data(month_start,today); previous_month=data(prev_start,prev_end)
    growth=round((month_data['revenue']-previous_month['revenue'])/previous_month['revenue']*100,1) if previous_month['revenue'] else None
    outstanding=[{'invoice':i,'balance':round(invoice_balance(i),2)} for i in Invoice.query.filter(Invoice.payment_status.in_(['Pending','Partial'])).order_by(Invoice.created_at.asc()).all() if invoice_balance(i)>0]
    return render_template('money_center.html',today_data=today_data,week_data=week_data,month_data=month_data,previous_month=previous_month,growth=growth,outstanding=outstanding)

@app.route('/quick-sale',methods=['GET','POST'])
@login_required
def quick_sale():
    if request.method=='POST':
        try:
            customer_id=request.form.get('customer_id',type=int); name=request.form.get('new_customer_name','').strip(); phone=request.form.get('new_customer_phone','').strip()
            if customer_id: customer=Customer.query.get_or_404(customer_id)
            else:
                if not name or not phone: raise ValueError('Select a customer or enter a name and phone.')
                customer=Customer.query.filter_by(phone=phone).first()
                if not customer: customer=Customer(name=name,phone=phone); db.session.add(customer); db.session.flush()
                else: customer.name=name
            service=Service.query.filter_by(id=request.form.get('service_id',type=int),is_active=True).first_or_404()
            staff=Staff.query.filter_by(id=request.form.get('staff_id',type=int),is_active=True).first_or_404()
            slot=datetime.now().replace(second=0,microsecond=0); chosen=None
            for _ in range(40):
                t=slot.strftime('%H:%M'); allowed,_=booking_allowed(date.today(),t,service.duration_minutes or 30)
                if allowed and not appointment_conflict(staff.id,date.today(),t,service.duration_minutes or 30): chosen=t; break
                slot+=timedelta(minutes=15)
            if not chosen: raise ValueError('No available slot for this staff member today.')
            discount=min(max(float(request.form.get('discount',0) or 0),0),service.price); tip=max(float(request.form.get('tip',0) or 0),0)
            tax=round(max(service.price-discount,0)*get_tax_rate()/100,2); total=round(max(service.price-discount,0)+tax+tip,2)
            method=request.form.get('payment_method','Cash'); paid=min(max(float(request.form.get('paid_amount',total) or total),0),total)
            appt=Appointment(customer_id=customer.id,staff_id=staff.id,service_id=service.id,appointment_date=date.today(),appointment_time=chosen,status='Completed',notes='Quick checkout / walk-in')
            db.session.add(appt); db.session.flush(); comm=StaffCommission.query.filter_by(staff_id=staff.id).first()
            inv=Invoice(appointment_id=appt.id,customer_id=customer.id,amount=service.price,discount=discount,tax=tax,tip=tip,total=total,payment_status='Pending',commission_rate=comm.commission_rate if comm else 0,payment_method=method)
            db.session.add(inv); db.session.flush(); db.session.add(InvoiceItem(invoice_id=inv.id,description=service.name,quantity=1,unit_price=service.price,total=service.price))
            if paid>0:
                db.session.add(InvoicePayment(invoice_id=inv.id,amount=round(paid,2),payment_method=method,notes='Quick checkout')); inv.payment_status='Paid' if paid>=total-0.01 else 'Partial'
            db.session.commit()
            if inv.payment_status=='Paid': award_loyalty_for_invoice(inv); db.session.commit()
            return redirect(url_for('view_invoice',id=inv.id))
        except (ValueError,TypeError,KeyError) as exc:
            db.session.rollback(); flash(str(exc) or 'Quick checkout failed.','danger')
    return render_template('quick_sale.html',customers=Customer.query.order_by(Customer.name).all(),staff_list=Staff.query.filter_by(is_active=True).order_by(Staff.name).all(),services=Service.query.filter_by(is_active=True).order_by(Service.name).all(),today_iso=date.today().isoformat(),tax_rate=get_tax_rate())

# ==================== CUSTOMERS ====================

@app.route('/customers')
@login_required
def customers():
    search = request.args.get('search', '').strip()
    segment = request.args.get('segment', '').strip()
    query = Customer.query
    if search:
        query = query.filter(db.or_(Customer.name.ilike(f'%{search}%'), Customer.phone.ilike(f'%{search}%')))
    rows = []
    for customer in query.order_by(Customer.name).all():
        metrics = _customer_metrics(customer.id)
        if metrics['visits'] == 0:
            category, label = 'new', 'New'
        elif metrics['lifetime_spend'] >= 25000:
            category, label = 'vip', 'VIP'
        elif metrics['days_since_visit'] is not None and metrics['days_since_visit'] >= 60:
            category, label = 'at_risk', 'At risk'
        else:
            category, label = 'returning', 'Returning'
        if segment and category != segment:
            continue
        rows.append({'customer':customer,'metrics':metrics,'category':category,'category_label':label,'next_action':customer_next_best_action(customer,metrics)})
    return render_template('customers.html', customers=[r['customer'] for r in rows], rows=rows, total_count=len(rows), search=search, segment=segment)

@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        try:
            customer = Customer(
                name=request.form['name'].strip(),
                phone=request.form['phone'].strip(),
                email=request.form.get('email', '').strip() or None,
                gender=request.form.get('gender') or None,
                address=request.form.get('address', '').strip() or None,
                notes=request.form.get('notes', '').strip() or None,
                date_of_birth=parse_optional_date(request.form.get('date_of_birth')),
                anniversary_date=parse_optional_date(request.form.get('anniversary_date')),
            )
            if not customer.name or not customer.phone:
                raise ValueError('Name and phone are required.')
            db.session.add(customer)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return render_template('customer_form.html', customer=None)
        except Exception:
            db.session.rollback()
            app.logger.exception('Customer creation failed')
            flash('Customer could not be saved. No changes were made.', 'danger')
            return render_template('customer_form.html', customer=None)
        flash('Customer added successfully!', 'success')
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=None)

@app.route('/customers/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_customer(id):
    customer = Customer.query.get_or_404(id)
    if request.method == 'POST':
        try:
            customer.name = request.form['name'].strip()
            customer.phone = request.form['phone'].strip()
            customer.email = request.form.get('email', '').strip() or None
            customer.gender = request.form.get('gender') or None
            customer.address = request.form.get('address', '').strip() or None
            customer.notes = request.form.get('notes', '').strip() or None
            customer.date_of_birth = parse_optional_date(request.form.get('date_of_birth'))
            customer.anniversary_date = parse_optional_date(request.form.get('anniversary_date'))
            if not customer.name or not customer.phone:
                raise ValueError('Name and phone are required.')
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return render_template('customer_form.html', customer=customer)
        except Exception:
            db.session.rollback()
            app.logger.exception('Customer update failed')
            flash('Customer could not be updated. No changes were made.', 'danger')
            return render_template('customer_form.html', customer=customer)
        flash('Customer updated successfully!', 'success')
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=customer)

@app.route('/customers/delete/<int:id>', methods=['POST'])
@login_required
def delete_customer(id):
    customer = Customer.query.get_or_404(id)
    if Appointment.query.filter_by(customer_id=id).first() or Invoice.query.filter_by(customer_id=id).first():
        flash('This customer has appointment or invoice history and cannot be deleted. Edit the customer instead.', 'warning')
        return redirect(url_for('customers'))
    try:
        db.session.delete(customer)
        db.session.commit()
        flash('Customer deleted.', 'info')
    except Exception:
        db.session.rollback()
        flash('Customer could not be deleted. No changes were made.', 'danger')
    return redirect(url_for('customers'))

# ==================== ADVANCED CRM & BUSINESS INTELLIGENCE ====================

def _customer_metrics(customer_id):
    """Build reusable CRM metrics from appointments, invoices and loyalty history."""
    appointments = Appointment.query.filter_by(customer_id=customer_id).order_by(
        Appointment.appointment_date.asc(), Appointment.appointment_time.asc()
    ).all()
    invoices = Invoice.query.filter_by(customer_id=customer_id).all()
    completed = [a for a in appointments if a.status == 'Completed']
    paid_revenue = round(sum(invoice_net_paid_amount(i) for i in invoices), 2)
    refunds = round(sum(invoice_refunded_amount(i) for i in invoices), 2)
    outstanding_balance = round(sum(invoice_balance(i) for i in invoices), 2)
    avg_ticket = round(paid_revenue / len(completed), 2) if completed else 0
    last_visit = completed[-1] if completed else None
    next_visit = next((a for a in appointments if a.status in ACTIVE_APPOINTMENT_STATUSES and a.appointment_date >= date.today()), None)

    service_counts = {}
    staff_counts = {}
    for appt in completed:
        if appt.service:
            service_counts[appt.service.name] = service_counts.get(appt.service.name, 0) + 1
        if appt.staff:
            staff_counts[appt.staff.name] = staff_counts.get(appt.staff.name, 0) + 1
    favorite_service = max(service_counts, key=service_counts.get) if service_counts else None
    most_used_staff = max(staff_counts, key=staff_counts.get) if staff_counts else None

    if len(completed) >= 2:
        intervals = [
            (completed[i].appointment_date - completed[i - 1].appointment_date).days
            for i in range(1, len(completed))
        ]
        avg_visit_interval = round(sum(intervals) / len(intervals), 1)
    else:
        avg_visit_interval = None

    days_since_visit = (date.today() - last_visit.appointment_date).days if last_visit else None
    loyalty = CustomerLoyalty.query.filter_by(customer_id=customer_id).first()
    return {
        'visits': len(completed),
        'paid_revenue': paid_revenue,
        'refunds': refunds,
        'avg_ticket': avg_ticket,
        'last_visit': last_visit,
        'next_visit': next_visit,
        'favorite_service': favorite_service,
        'most_used_staff': most_used_staff,
        'avg_visit_interval_days': avg_visit_interval,
        'days_since_visit': days_since_visit,
        'loyalty_points': loyalty.points if loyalty else 0,
        'lifetime_spend': round(loyalty.lifetime_spend, 2) if loyalty else paid_revenue,
        'outstanding_balance': outstanding_balance,
        'no_shows': sum(1 for a in appointments if a.status == 'No-Show'),
        'cancelled': sum(1 for a in appointments if a.status == 'Cancelled'),
    }

@app.route('/api/crm/summary')
@login_required
def crm_summary():
    """Authenticated CRM summary API; intentionally does not alter existing UI."""
    customers = Customer.query.order_by(Customer.name).all()
    rows = []
    for customer in customers:
        metrics = _customer_metrics(customer.id)
        rows.append({
            'id': customer.id,
            'name': customer.name,
            'phone': customer.phone,
            'visits': metrics['visits'],
            'paid_revenue': metrics['paid_revenue'],
            'avg_ticket': metrics['avg_ticket'],
            'last_visit': metrics['last_visit'].appointment_date.isoformat() if metrics['last_visit'] else None,
            'next_visit': metrics['next_visit'].appointment_date.isoformat() if metrics['next_visit'] else None,
            'favorite_service': metrics['favorite_service'],
            'avg_visit_interval_days': metrics['avg_visit_interval_days'],
            'days_since_visit': metrics['days_since_visit'],
            'loyalty_points': metrics['loyalty_points'],
            'no_shows': metrics['no_shows'],
            'cancelled': metrics['cancelled'],
        })
    return jsonify({
        'customers': rows,
        'total_customers': len(rows),
        'active_customers': sum(1 for r in rows if r['next_visit'] or (r['days_since_visit'] is not None and r['days_since_visit'] <= 90)),
        'repeat_customers': sum(1 for r in rows if r['visits'] >= 2),
    })


@app.route('/api/business-intelligence')
@login_required
def business_intelligence():
    """Authenticated BI API for operational and financial decision support."""
    today = date.today()
    start_text = request.args.get('start', (today - timedelta(days=29)).isoformat())
    end_text = request.args.get('end', today.isoformat())
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
        if end < start:
            raise ValueError
    except ValueError:
        return jsonify({'error': 'Invalid date range. Use YYYY-MM-DD and ensure end >= start.'}), 400

    invoices = Invoice.query.filter(
        func.date(Invoice.created_at) >= start,
        func.date(Invoice.created_at) <= end
    ).all()
    appointments = Appointment.query.filter(
        Appointment.appointment_date >= start, Appointment.appointment_date <= end
    ).all()
    expenses = Expense.query.filter(
        Expense.expense_date >= start, Expense.expense_date <= end
    ).all()

    gross_collected = round(sum(invoice_net_paid_amount(i) + invoice_refunded_amount(i) for i in invoices), 2)
    refunds = round(sum(invoice_refunded_amount(i) for i in invoices), 2)
    net_revenue = round(gross_collected - refunds, 2)
    expense_total = round(sum(e.amount for e in expenses), 2)
    commissions = 0.0
    for member in Staff.query.all():
        settings = StaffCommission.query.filter_by(staff_id=member.id).first()
        rate = settings.commission_rate if settings else 0
        member_service_revenue = 0.0
        for inv in invoices:
            if not inv.appointment or inv.appointment.staff_id != member.id:
                continue
            for item in inv.items:
                if not InventorySaleLine.query.filter_by(invoice_item_id=item.id).first():
                    member_service_revenue += item.total * (invoice_net_paid_amount(inv) / inv.total) if inv.total else 0
        commissions += member_service_revenue * rate / 100
    commissions = round(commissions, 2)

    completed = sum(1 for a in appointments if a.status == 'Completed')
    no_shows = sum(1 for a in appointments if a.status == 'No-Show')
    cancelled = sum(1 for a in appointments if a.status == 'Cancelled')
    scheduled_or_completed = completed + sum(1 for a in appointments if a.status == 'Scheduled')
    service_revenue = {}
    for invoice in invoices:
        if invoice_net_paid_amount(invoice) <= 0:
            continue
        if invoice.appointment and invoice.appointment.service:
            service_item = next(
                (item for item in invoice.items
                 if not InventorySaleLine.query.filter_by(invoice_item_id=item.id).first()),
                None
            )
            if service_item:
                service_revenue[invoice.appointment.service.name] = (
                    service_revenue.get(invoice.appointment.service.name, 0)
                    + (service_item.total * (invoice_net_paid_amount(invoice) / invoice.total) if invoice.total else 0)
                )

    inventory_value = round(sum((i.stock_qty or 0) * (i.cost_price or 0) for i in InventoryItem.query.filter_by(is_active=True).all()), 2)
    low_stock = InventoryItem.query.filter(
        InventoryItem.is_active == True, InventoryItem.stock_qty <= InventoryItem.reorder_level
    ).count()

    customer_ids = {i.customer_id for i in invoices if i.customer_id and invoice_net_paid_amount(i) > 0}
    repeat_ids = set()
    for customer_id in customer_ids:
        if Appointment.query.filter_by(customer_id=customer_id, status='Completed').count() >= 2:
            repeat_ids.add(customer_id)

    return jsonify({
        'range': {'start': start.isoformat(), 'end': end.isoformat()},
        'financial': {
            'gross_collected': gross_collected,
            'refunds': refunds,
            'net_revenue': net_revenue,
            'expenses': expense_total,
            'profit_before_tax_and_other_adjustments': round(net_revenue - expense_total, 2),            'average_paid_invoice': round(net_revenue / len([i for i in invoices if invoice_net_paid_amount(i) > 0]), 2) if any(invoice_net_paid_amount(i) > 0 for i in invoices) else 0,            'commissions': commissions,
        },
        'appointments': {
            'total': len(appointments),
            'completed': completed,
            'no_shows': no_shows,
            'cancelled': cancelled,
            'completion_rate': round(completed / len(appointments) * 100, 2) if appointments else 0,
            'no_show_rate': round(no_shows / len(appointments) * 100, 2) if appointments else 0,
        },
        'customers': {
            'paying_customers': len(customer_ids),
            'repeat_customer_rate': round(len(repeat_ids) / len(customer_ids) * 100, 2) if customer_ids else 0,
        },
        'inventory': {
            'stock_value_at_cost': inventory_value,
            'low_stock_items': low_stock,
        },
        'service_revenue': [
            {'service': name, 'revenue': round(value, 2)}
            for name, value in sorted(service_revenue.items(), key=lambda x: (-x[1], x[0]))
        ],
    })


# ==================== ADVANCED RETENTION & PERFORMANCE INTELLIGENCE ====================

@app.route('/api/crm/retention')
@login_required
def crm_retention():
    """Return actionable customer-recall segments without changing the existing UI."""
    today = date.today()
    segments = {'new': [], 'active': [], 'due': [], 'at_risk': [], 'lost': []}
    customers = Customer.query.order_by(Customer.name).all()

    for customer in customers:
        metrics = _customer_metrics(customer.id)
        visits = metrics['visits']
        days = metrics['days_since_visit']
        interval = metrics['avg_visit_interval_days']

        if visits == 0:
            segment = 'new'
        elif days is None:
            segment = 'new'
        elif days <= max(30, int((interval or 30) * 1.25)):
            segment = 'active'
        elif days <= max(60, int((interval or 30) * 2.0)):
            segment = 'due'
        elif days <= 180:
            segment = 'at_risk'
        else:
            segment = 'lost'

        segments[segment].append({
            'id': customer.id,
            'name': customer.name,
            'phone': customer.phone,
            'visits': visits,
            'lifetime_spend': metrics['lifetime_spend'],
            'last_visit': metrics['last_visit'].appointment_date.isoformat() if metrics['last_visit'] else None,
            'days_since_visit': days,
            'avg_visit_interval_days': interval,
            'favorite_service': metrics['favorite_service'],
            'no_shows': metrics['no_shows']
        })

    return jsonify({
        'generated_at': today.isoformat(),
        'segments': segments,
        'counts': {name: len(rows) for name, rows in segments.items()}
    })


@app.route('/api/business-intelligence/services')
@login_required
def service_profitability():
    """Service-level revenue and operational metrics for the BI layer."""
    today = date.today()
    start_text = request.args.get('start', (today - timedelta(days=29)).isoformat())
    end_text = request.args.get('end', today.isoformat())
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
        if end < start:
            raise ValueError
    except ValueError:
        return jsonify({'error': 'Invalid date range. Use YYYY-MM-DD and ensure end >= start.'}), 400

    services = Service.query.order_by(Service.name).all()
    rows = []
    for service in services:
        appts = Appointment.query.filter(
            Appointment.service_id == service.id,
            Appointment.appointment_date >= start,
            Appointment.appointment_date <= end
        ).all()
        completed = [a for a in appts if a.status == 'Completed']
        invoices = Invoice.query.join(Appointment, Invoice.appointment_id == Appointment.id).filter(
            Appointment.service_id == service.id,
            Invoice.created_at >= datetime.combine(start, datetime.min.time()),
            Invoice.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time())
        ).all()
        collected = round(sum(invoice_net_paid_amount(i) for i in invoices), 2)
        refunds = round(sum(invoice_refunded_amount(i) for i in invoices), 2)
        # invoice_net_paid_amount() is already net of refunds.
        net = collected
        rows.append({
            'id': service.id,
            'service': service.name,
            'category': service.category,
            'price': round(service.price, 2),
            'duration_minutes': service.duration_minutes,
            'appointments': len(appts),
            'completed': len(completed),
            'no_shows': sum(1 for a in appts if a.status == 'No-Show'),
            'completion_rate': round(len(completed) / len(appts) * 100, 2) if appts else 0,
            'net_revenue': net,
            'revenue_per_completed_visit': round(net / len(completed), 2) if completed else 0,
            'revenue_per_hour': round(net / (sum(a.service.duration_minutes for a in completed) / 60), 2)
                if completed and service.duration_minutes else 0
        })

    rows.sort(key=lambda x: (-x['net_revenue'], x['service'].lower()))
    return jsonify({'range': {'start': start.isoformat(), 'end': end.isoformat()}, 'services': rows})


@app.route('/api/business-intelligence/staff')
@login_required
def staff_intelligence():
    """Staff-level operational metrics; no UI changes required."""
    today = date.today()
    start_text = request.args.get('start', today.replace(day=1).isoformat())
    end_text = request.args.get('end', today.isoformat())
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
        if end < start:
            raise ValueError
    except ValueError:
        return jsonify({'error': 'Invalid date range. Use YYYY-MM-DD and ensure end >= start.'}), 400

    rows = []
    for member in Staff.query.order_by(Staff.name).all():
        appts = Appointment.query.filter(
            Appointment.staff_id == member.id,
            Appointment.appointment_date >= start,
            Appointment.appointment_date <= end
        ).all()
        completed = [a for a in appts if a.status == 'Completed']
        invoices = Invoice.query.join(Appointment, Invoice.appointment_id == Appointment.id).filter(
            Appointment.staff_id == member.id,
            Invoice.created_at >= datetime.combine(start, datetime.min.time()),
            Invoice.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time())
        ).all()
        collected = round(sum(invoice_net_paid_amount(i) for i in invoices), 2)
        refunds = round(sum(invoice_refunded_amount(i) for i in invoices), 2)
        # invoice_net_paid_amount() is already net of refunds.
        net = collected
        commission_settings = StaffCommission.query.filter_by(staff_id=member.id).first()
        rate = commission_settings.commission_rate if commission_settings else 0
        commission = round(max(net, 0) * rate / 100, 2)
        service_minutes = sum(a.service.duration_minutes for a in completed if a.service and a.service.duration_minutes)
        rows.append({
            'id': member.id,
            'staff': member.name,
            'active': member.is_active,
            'appointments': len(appts),
            'completed': len(completed),
            'no_shows': sum(1 for a in appts if a.status == 'No-Show'),
            'cancelled': sum(1 for a in appts if a.status == 'Cancelled'),
            'completion_rate': round(len(completed) / len(appts) * 100, 2) if appts else 0,
            'net_revenue': net,
            'revenue_per_completed_visit': round(net / len(completed), 2) if completed else 0,
            'revenue_per_service_hour': round(net / (service_minutes / 60), 2) if service_minutes else 0,
            'commission_rate': rate,
            'estimated_commission': commission
        })

    return jsonify({'range': {'start': start.isoformat(), 'end': end.isoformat()}, 'staff': rows})


# ==================== CUSTOMER PROFILE ====================

@app.route('/customers/<int:id>')
@login_required
def customer_detail(id):
    customer = Customer.query.get_or_404(id)
    customer_appointments = Appointment.query.filter_by(customer_id=id).order_by(
        Appointment.appointment_date.desc(), Appointment.appointment_time.desc()
    ).all()
    customer_invoices = Invoice.query.filter_by(customer_id=id).order_by(Invoice.created_at.desc()).all()
    completed_visits = Appointment.query.filter_by(customer_id=id, status='Completed').count()
    # Use the same payment/refund accounting as invoices and BI. This prevents
    # refunded revenue from remaining in the customer profile and includes
    # partial-payment balances.
    total_spend = round(sum(invoice_net_paid_amount(i) for i in customer_invoices), 2)
    pending_amount = round(sum(invoice_balance(i) for i in customer_invoices), 2)
    last_visit = Appointment.query.filter_by(customer_id=id, status='Completed').order_by(
        Appointment.appointment_date.desc()
    ).first()
    crm = _customer_metrics(id)
    return render_template('customer_detail.html', customer=customer,
                           appointments=customer_appointments, invoices=customer_invoices,
                           completed_visits=completed_visits, total_spend=total_spend,
                           pending_amount=pending_amount, last_visit=last_visit,
                           crm=crm, customer_next_action=customer_next_best_action(customer, crm))


# ==================== EXPENSES ====================

@app.route('/expenses')
@login_required
def expenses():
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    try:
        month_start = datetime.strptime(month + '-01', '%Y-%m-%d').date()
    except ValueError:
        month_start = date.today().replace(day=1)
        month = month_start.strftime('%Y-%m')
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    expenses_list = Expense.query.filter(
        Expense.expense_date >= month_start, Expense.expense_date < next_month
    ).order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    total_expenses = sum(e.amount for e in expenses_list)
    return render_template('expenses.html', expenses=expenses_list,
                           total_expenses=total_expenses, month=month)

@app.route('/expenses/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    if request.method == 'POST':
        try:
            amount = float(request.form['amount'])
            expense_date = datetime.strptime(request.form['expense_date'], '%Y-%m-%d').date()
            if amount <= 0:
                raise ValueError
        except (ValueError, TypeError):
            flash('Enter a valid positive expense amount and date.', 'danger')
            return redirect(url_for('add_expense'))
        expense = Expense(title=request.form['title'].strip(),
                          category=request.form['category'].strip(),
                          amount=amount, expense_date=expense_date,
                          notes=request.form.get('notes'))
        db.session.add(expense)
        db.session.commit()
        flash('Expense added successfully!', 'success')
        return redirect(url_for('expenses'))
    return render_template('expense_form.html', expense=None)

@app.route('/expenses/delete/<int:id>', methods=['POST'])
@login_required
def delete_expense(id):
    expense = Expense.query.get_or_404(id)
    db.session.delete(expense)
    db.session.commit()
    flash('Expense deleted.', 'info')
    return redirect(url_for('expenses'))


# ==================== SERVICES ====================

@app.route('/services')
@login_required
def services():
    services_list = Service.query.order_by(Service.category, Service.name).all()
    return render_template('services.html', services=services_list)

@app.route('/services/add', methods=['GET', 'POST'])
@login_required
def add_service():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            duration = int(request.form.get('duration_minutes', 30))
            price = float(request.form.get('price', 0))
            if not name or duration <= 0 or price < 0:
                raise ValueError
            service = Service(
                name=name,
                description=request.form.get('description'),
                duration_minutes=duration,
                price=price,
                category=request.form.get('category'),
                retention_min_days=max(1,int(request.form.get('retention_min_days',30))),
                retention_max_days=max(1,int(request.form.get('retention_max_days',45))),
                is_active=True,
            )
            db.session.add(service)
            db.session.commit()
            flash('Service added successfully!', 'success')
            return redirect(url_for('services'))
        except (KeyError, TypeError, ValueError):
            db.session.rollback()
            flash('Enter a valid service name, duration and non-negative price.', 'danger')
            return redirect(url_for('add_service'))
    return render_template('service_form.html', service=None)

@app.route('/services/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_service(id):
    service = Service.query.get_or_404(id)
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            duration = int(request.form.get('duration_minutes', 30))
            price = float(request.form.get('price', 0))
            if not name or duration <= 0 or price < 0:
                raise ValueError
            service.name = name
            service.description = request.form.get('description')
            service.duration_minutes = duration
            service.price = price
            service.category = request.form.get('category')
            service.retention_min_days = max(1,int(request.form.get('retention_min_days',30)))
            service.retention_max_days = max(service.retention_min_days,int(request.form.get('retention_max_days',45)))
            service.is_active = 'is_active' in request.form
            db.session.commit()
            flash('Service updated!', 'success')
            return redirect(url_for('services'))
        except (KeyError, TypeError, ValueError):
            db.session.rollback()
            flash('Enter a valid service name, duration and non-negative price.', 'danger')
            return redirect(url_for('edit_service', id=id))
    return render_template('service_form.html', service=service)
@app.route('/services/delete/<int:id>', methods=['POST'])
@login_required
def delete_service(id):
    service = Service.query.get_or_404(id)
    if Appointment.query.filter_by(service_id=id).first():
        flash('This service is used by appointment history and cannot be deleted. Mark it inactive instead.', 'warning')
        return redirect(url_for('services'))
    try:
        db.session.delete(service)
        db.session.commit()
        flash('Service deleted.', 'info')
    except Exception:
        db.session.rollback()
        flash('Service could not be deleted. No changes were made.', 'danger')
    return redirect(url_for('services'))

# ==================== STAFF ====================

@app.route('/staff')
@login_required
def staff():
    staff_list = Staff.query.order_by(Staff.name).all()
    return render_template('staff.html', staff_list=staff_list)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
def add_staff():
    if request.method == 'POST':
        member = Staff(
            name=request.form['name'],
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            specialty=request.form.get('specialty'),
            is_active=True
        )
        db.session.add(member)
        db.session.commit()
        flash('Staff member added!', 'success')
        return redirect(url_for('staff'))
    return render_template('staff_form.html', staff=None)

@app.route('/staff/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_staff(id):
    member = Staff.query.get_or_404(id)
    if request.method == 'POST':
        member.name = request.form['name']
        member.phone = request.form.get('phone')
        member.email = request.form.get('email')
        member.specialty = request.form.get('specialty')
        member.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Staff updated!', 'success')
        return redirect(url_for('staff'))
    return render_template('staff_form.html', staff=member)

@app.route('/staff/delete/<int:id>', methods=['POST'])
@login_required
def delete_staff(id):
    member = Staff.query.get_or_404(id)
    has_history = (
        Appointment.query.filter_by(staff_id=id).first()
        or StaffAttendance.query.filter_by(staff_id=id).first()
        or StaffCommission.query.filter_by(staff_id=id).first()
        or UserStaffLink.query.filter_by(staff_id=id).first()
    )
    if has_history:
        flash('This staff member has history or a linked account and cannot be deleted. Deactivate the staff member instead.', 'warning')
        return redirect(url_for('staff'))
    try:
        db.session.delete(member)
        db.session.commit()
        flash('Staff member deleted.', 'info')
    except Exception:
        db.session.rollback()
        flash('Staff member could not be deleted. No changes were made.', 'danger')
    return redirect(url_for('staff'))

# ==================== STAFF ACCOUNTS ====================

@app.route('/staff/<int:id>/account', methods=['GET', 'POST'])
@admin_required
def create_staff_account(id):
    member = Staff.query.get_or_404(id)
    existing_link = UserStaffLink.query.filter_by(staff_id=member.id).first()
    if existing_link:
        flash('This staff member already has a login account.', 'info')
        return redirect(url_for('staff'))
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        if len(username) < 3 or len(password) < 8:
            flash('Username must be at least 3 characters and password at least 8 characters.', 'danger')
            return redirect(url_for('create_staff_account', id=id))
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('create_staff_account', id=id))
        role = request.form.get('role', 'staff').strip().lower()
        if role not in {'manager', 'receptionist', 'staff'}:
            role = 'staff'
        user = User(username=username, password_hash=generate_password_hash(password), role=role)
        db.session.add(user)
        db.session.flush()
        db.session.add(UserStaffLink(user_id=user.id, staff_id=member.id))
        db.session.commit()
        flash(f'Login account created for {member.name}.', 'success')
        return redirect(url_for('staff'))
    return render_template('staff_account.html', member=member)

# ==================== APPOINTMENTS ====================

@app.route('/waitlist', methods=['GET', 'POST'])
@login_required
def waitlist():
    if request.method == 'POST':
        try:
            customer_id = int(request.form['customer_id'])
            service_id = int(request.form['service_id'])
            staff_text = request.form.get('preferred_staff_id', '').strip()
            preferred_staff_id = int(staff_text) if staff_text else None
            date_text = request.form.get('preferred_date', '').strip()
            preferred_date = datetime.strptime(date_text, '%Y-%m-%d').date() if date_text else None
            preferred_time = request.form.get('preferred_time', '').strip() or None
            Customer.query.get_or_404(customer_id)
            Service.query.filter_by(id=service_id, is_active=True).first_or_404()
            if preferred_staff_id:
                Staff.query.filter_by(id=preferred_staff_id, is_active=True).first_or_404()
            if preferred_date and preferred_date < date.today():
                raise ValueError('Preferred date cannot be in the past.')
            db.session.add(WaitlistEntry(
                customer_id=customer_id, service_id=service_id, preferred_staff_id=preferred_staff_id,
                preferred_date=preferred_date, preferred_time=preferred_time,
                notes=request.form.get('notes', '').strip() or None
            ))
            db.session.commit()
            flash('Customer added to the waitlist.', 'success')
            return redirect(url_for('waitlist'))
        except (KeyError, TypeError, ValueError):
            db.session.rollback()
            flash('Please choose a valid customer, service, and preferred slot.', 'danger')
    rows = WaitlistEntry.query.filter(WaitlistEntry.status == 'Open').order_by(WaitlistEntry.preferred_date.is_(None), WaitlistEntry.preferred_date, WaitlistEntry.created_at).all()
    return render_template('waitlist.html', rows=rows, customers=Customer.query.order_by(Customer.name).all(),
        services=Service.query.filter_by(is_active=True).order_by(Service.name).all(),
        staff_list=Staff.query.filter_by(is_active=True).order_by(Staff.name).all(), today=date.today())

@app.route('/waitlist/<int:id>/book', methods=['POST'])
@login_required
def book_waitlist(id):
    row = WaitlistEntry.query.get_or_404(id)
    if row.status != 'Open':
        flash('This waitlist entry is no longer open.', 'warning')
        return redirect(url_for('waitlist'))
    try:
        appointment_date = datetime.strptime(request.form['appointment_date'], '%Y-%m-%d').date()
        appointment_time = request.form['appointment_time']
        staff_id = int(request.form['staff_id'])
        service = Service.query.filter_by(id=row.service_id, is_active=True).first_or_404()
        Staff.query.filter_by(id=staff_id, is_active=True).first_or_404()
        allowed, reason = booking_allowed(appointment_date, appointment_time, service.duration_minutes or 30)
        if not allowed:
            raise ValueError(reason)
        conflict = appointment_conflict(staff_id, appointment_date, appointment_time, service.duration_minutes or 30)
        if conflict:
            raise ValueError(conflict)
        appt = Appointment(customer_id=row.customer_id, staff_id=staff_id, service_id=row.service_id,
                           appointment_date=appointment_date, appointment_time=appointment_time, status='Confirmed',
                           notes=row.notes)
        db.session.add(appt)
        row.status = 'Booked'
        db.session.commit()
        flash('Waitlist customer booked and removed from the open list.', 'success')
    except (KeyError, TypeError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc) or 'Could not book this waitlist entry.', 'danger')
    return redirect(url_for('waitlist'))

@app.route('/waitlist/<int:id>/cancel', methods=['POST'])
@login_required
def cancel_waitlist(id):
    row = WaitlistEntry.query.get_or_404(id)
    if row.status == 'Open':
        row.status = 'Cancelled'
        db.session.commit()
    return redirect(url_for('waitlist'))

@app.route('/smart-schedule')
@login_required
def smart_schedule():
    selected_text = request.args.get('date', date.today().isoformat())
    try:
        selected = datetime.strptime(selected_text, '%Y-%m-%d').date()
    except ValueError:
        selected = date.today()
    service_id = request.args.get('service_id', type=int)
    preferred_staff_id = request.args.get('staff_id', type=int)
    slots = []
    if service_id:
        try:
            slots = smart_schedule_slots(service_id, selected, preferred_staff_id, limit=12)
        except Exception:
            slots = []
    return render_template('smart_schedule.html', services=Service.query.filter_by(is_active=True).order_by(Service.name).all(),
        staff_list=Staff.query.filter_by(is_active=True).order_by(Staff.name).all(), selected=selected,
        service_id=service_id, preferred_staff_id=preferred_staff_id, slots=slots)

@app.route('/api/smart-schedule')
@login_required
def smart_schedule_api():
    service_id = request.args.get('service_id', type=int)
    staff_id = request.args.get('staff_id', type=int)
    date_text = request.args.get('date', date.today().isoformat())
    if not service_id:
        return jsonify({'ok': False, 'error': 'service_id is required'}), 400
    try:
        target_date = datetime.strptime(date_text, '%Y-%m-%d').date()
        return jsonify({'ok': True, 'slots': smart_schedule_slots(service_id, target_date, staff_id, limit=12)})
    except ValueError:
        return jsonify({'ok': False, 'error': 'date must be YYYY-MM-DD'}), 400
@app.route('/appointments')
@login_required
def appointments():
    status_filter=request.args.get('status',''); date_filter=request.args.get('date','')
    query=Appointment.query
    if status_filter:
        query=query.filter(Appointment.status.in_(['Booked','Scheduled']) if status_filter=='Booked' else Appointment.status==status_filter)
    if date_filter:
        try: query=query.filter_by(appointment_date=datetime.strptime(date_filter,'%Y-%m-%d').date())
        except ValueError: flash('Invalid appointment date.','warning'); date_filter=''
    return render_template('appointments.html',appointments=query.order_by(Appointment.appointment_date.desc(),Appointment.appointment_time).all(),status_filter=status_filter,date_filter=date_filter,status_options=APPOINTMENT_STATUSES,today=date.today())

@app.route('/appointments/add',methods=['GET','POST'])
@login_required
def add_appointment():
    if request.method=='POST':
        try:
            appointment_date=datetime.strptime(request.form['appointment_date'],'%Y-%m-%d').date(); appointment_time=request.form['appointment_time']; datetime.strptime(appointment_time,'%H:%M')
            staff_id=int(request.form['staff_id']); service_id=int(request.form['service_id']); customer_id=int(request.form['customer_id'])
            service=Service.query.filter_by(id=service_id,is_active=True).first_or_404(); Staff.query.filter_by(id=staff_id,is_active=True).first_or_404(); Customer.query.get_or_404(customer_id)
            allowed,reason=booking_allowed(appointment_date,appointment_time,service.duration_minutes or 30)
            if not allowed: raise ValueError(reason)
            conflict=appointment_conflict(staff_id,appointment_date,appointment_time,service.duration_minutes or 30)
            if conflict: raise ValueError(conflict)
            status=normalize_appointment_status(request.form.get('status','Booked')); status='Scheduled' if status=='Booked' else status; recurrence=request.form.get('recurrence_rule','None')
            end_text=request.form.get('recurrence_end_date','').strip(); recurrence_end=datetime.strptime(end_text,'%Y-%m-%d').date() if end_text else None
            if recurrence not in {'None','Weekly','Biweekly','Monthly'}: recurrence='None'
            if recurrence!='None' and not recurrence_end: raise ValueError('Choose an end date for recurring appointments.')
            if recurrence_end and recurrence_end<appointment_date: raise ValueError('Recurring end date must be after the first appointment.')
            created=[]; current=appointment_date
            while True:
                allowed,_=booking_allowed(current,appointment_time,service.duration_minutes or 30); conflict=appointment_conflict(staff_id,current,appointment_time,service.duration_minutes or 30)
                if allowed and not conflict:
                    created.append(Appointment(customer_id=customer_id,staff_id=staff_id,service_id=service_id,appointment_date=current,appointment_time=appointment_time,notes=request.form.get('notes'),status=status,recurrence_rule=recurrence,recurrence_end_date=recurrence_end))
                if recurrence=='None' or not recurrence_end or current>=recurrence_end: break
                if recurrence=='Weekly': current+=timedelta(days=7)
                elif recurrence=='Biweekly': current+=timedelta(days=14)
                else:
                    nm=(current.replace(day=1)+timedelta(days=32)).replace(day=1); current=nm.replace(day=min(current.day,28))
            if not created: raise ValueError('No available appointment slots matched this request.')
            db.session.add_all(created); db.session.commit(); flash(f'{len(created)} appointment(s) booked.','success'); return redirect(url_for('appointments'))
        except (KeyError,TypeError,ValueError) as exc:
            db.session.rollback(); flash(str(exc) or 'Please enter valid appointment details.','danger')
    return render_template('appointment_form.html',appointment=None,customers=Customer.query.order_by(Customer.name).all(),staff_list=Staff.query.filter_by(is_active=True).order_by(Staff.name).all(),services=Service.query.filter_by(is_active=True).order_by(Service.name).all(),status_options=APPOINTMENT_STATUSES,recurrence_options=['None','Weekly','Biweekly','Monthly'])

@app.route('/appointments/edit/<int:id>',methods=['GET','POST'])
@login_required
def edit_appointment(id):
    appt=Appointment.query.get_or_404(id); existing_invoice=Invoice.query.filter_by(appointment_id=appt.id).first()
    if request.method=='POST':
        if existing_invoice and appt.status=='Completed': flash('Completed appointments with invoices are locked. Edit the invoice instead.','warning'); return redirect(url_for('appointments'))
        try:
            appt_date=datetime.strptime(request.form['appointment_date'],'%Y-%m-%d').date(); appt_time=request.form['appointment_time']; datetime.strptime(appt_time,'%H:%M')
            staff_id=int(request.form['staff_id']); service_id=int(request.form['service_id']); customer_id=int(request.form['customer_id'])
            service=Service.query.filter_by(id=service_id,is_active=True).first_or_404(); Staff.query.filter_by(id=staff_id,is_active=True).first_or_404(); Customer.query.get_or_404(customer_id)
            allowed,reason=booking_allowed(appt_date,appt_time,service.duration_minutes or 30)
            if not allowed: raise ValueError(reason)
            conflict=appointment_conflict(staff_id,appt_date,appt_time,service.duration_minutes or 30,exclude_id=appt.id)
            if conflict: raise ValueError(conflict)
            status=normalize_appointment_status(request.form.get('status','Booked'));
            if status not in APPOINTMENT_STATUSES: raise ValueError('Invalid appointment status.')
            appt.customer_id=customer_id; appt.staff_id=staff_id; appt.service_id=service_id; appt.appointment_date=appt_date; appt.appointment_time=appt_time; appt.status=status; appt.notes=request.form.get('notes')
            appt.recurrence_rule=request.form.get('recurrence_rule','None'); end_text=request.form.get('recurrence_end_date','').strip(); appt.recurrence_end_date=datetime.strptime(end_text,'%Y-%m-%d').date() if end_text else None
            if status=='Completed' and not existing_invoice:
                comm=StaffCommission.query.filter_by(staff_id=appt.staff_id).first(); price=service.price; tax=round(price*get_tax_rate()/100,2)
                inv=Invoice(appointment_id=appt.id,customer_id=appt.customer_id,amount=price,discount=0,tax=tax,tip=0,total=round(price+tax,2),payment_status='Pending',commission_rate=comm.commission_rate if comm else 0)
                db.session.add(inv); db.session.flush(); db.session.add(InvoiceItem(invoice_id=inv.id,description=service.name,quantity=1,unit_price=price,total=price))
            if status in {'Cancelled','No-Show'} and existing_invoice and invoice_net_paid_amount(existing_invoice)>0: raise ValueError('Refund the invoice before cancelling this appointment.')
            if status in {'Cancelled','No-Show'} and existing_invoice: db.session.delete(existing_invoice)
            db.session.commit(); flash('Appointment updated.','success'); return redirect(url_for('appointments'))
        except (KeyError,TypeError,ValueError) as exc:
            db.session.rollback(); flash(str(exc) or 'Please enter valid appointment details.','danger')
    return render_template('appointment_form.html',appointment=appt,customers=Customer.query.order_by(Customer.name).all(),staff_list=Staff.query.filter_by(is_active=True).order_by(Staff.name).all(),services=Service.query.filter_by(is_active=True).order_by(Service.name).all(),status_options=APPOINTMENT_STATUSES,recurrence_options=['None','Weekly','Biweekly','Monthly'])

@app.route('/appointments/status/<int:id>/<status>',methods=['POST'])
@login_required
def update_appointment_status(id,status):
    status=normalize_appointment_status(status)
    if status=='Booked': status='Scheduled'
    if status not in APPOINTMENT_STATUSES: return jsonify({'ok':False,'error':'Invalid appointment status.'}),400
    appt=Appointment.query.get_or_404(id); existing=Invoice.query.filter_by(appointment_id=appt.id).first()
    if status=='Completed' and appt.appointment_date>date.today(): return jsonify({'ok':False,'error':'Future appointment cannot be completed.'}),400
    if status in {'Cancelled','No-Show'} and existing and invoice_net_paid_amount(existing)>0: return jsonify({'ok':False,'error':'Refund the invoice first.'}),409
    try:
        appt.status=status
        if status=='Completed' and not existing:
            service=Service.query.get(appt.service_id); comm=StaffCommission.query.filter_by(staff_id=appt.staff_id).first(); tax=round(service.price*get_tax_rate()/100,2)
            inv=Invoice(appointment_id=appt.id,customer_id=appt.customer_id,amount=service.price,discount=0,tax=tax,tip=0,total=round(service.price+tax,2),payment_status='Pending',commission_rate=comm.commission_rate if comm else 0)
            db.session.add(inv); db.session.flush(); db.session.add(InvoiceItem(invoice_id=inv.id,description=service.name,quantity=1,unit_price=service.price,total=service.price))
        if status in {'Cancelled','No-Show'} and existing and invoice_net_paid_amount(existing)<=0: db.session.delete(existing)
        if status == 'Cancelled':
            matching_waitlist = WaitlistEntry.query.filter_by(service_id=appt.service_id, status='Open').filter(
                db.or_(WaitlistEntry.preferred_staff_id.is_(None), WaitlistEntry.preferred_staff_id == appt.staff_id)
            ).order_by(WaitlistEntry.created_at).limit(3).all()
            if matching_waitlist:
                flash(f'{len(matching_waitlist)} waitlist customer(s) match this cancelled slot. Open Waitlist to fill it.', 'warning')
        db.session.commit(); result={'ok':True,'status':status}; return jsonify(result) if request.is_json else redirect(request.referrer or url_for('appointments'))
    except Exception:
        db.session.rollback();
        return (jsonify({'ok':False,'error':'Could not update appointment. No changes were saved.'}),500) if request.is_json else redirect(url_for('appointments'))

@app.route('/invoices')
@login_required
def invoices():
    invoices_list = Invoice.query.order_by(Invoice.created_at.desc()).all()
    return render_template('invoices.html', invoices=invoices_list)

@app.route('/api/staff/<int:staff_id>/availability', methods=['GET','POST'])
@login_required
def staff_availability_api(staff_id):
    Staff.query.get_or_404(staff_id)
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        try:
            day = int(payload.get('day_of_week'))
            start_time = payload.get('start_time', '09:00')
            end_time = payload.get('end_time', '20:00')
            is_working = bool(payload.get('is_working', True))
            datetime.strptime(start_time, '%H:%M')
            datetime.strptime(end_time, '%H:%M')
            if day not in range(7) or start_time >= end_time:
                raise ValueError
            row = StaffSchedule.query.filter_by(staff_id=staff_id, day_of_week=day).first()
            if not row:
                row = StaffSchedule(staff_id=staff_id, day_of_week=day)
                db.session.add(row)
            row.start_time = start_time
            row.end_time = end_time
            row.is_working = is_working
            db.session.commit()
            return jsonify({'ok': True, 'day_of_week': day, 'start_time': start_time, 'end_time': end_time, 'is_working': is_working})
        except (TypeError, ValueError):
            db.session.rollback()
            return jsonify({'ok': False, 'error': 'Invalid staff availability.'}), 400
    rows = StaffSchedule.query.filter_by(staff_id=staff_id).order_by(StaffSchedule.day_of_week).all()
    breaks = StaffBreak.query.filter_by(staff_id=staff_id).order_by(StaffBreak.day_of_week, StaffBreak.start_time).all()
    return jsonify({
        'availability': [{'day_of_week': r.day_of_week, 'start_time': r.start_time, 'end_time': r.end_time, 'is_working': r.is_working} for r in rows],
        'breaks': [{'id': b.id, 'day_of_week': b.day_of_week, 'start_time': b.start_time, 'end_time': b.end_time, 'is_active': b.is_active} for b in breaks]
    })

@app.route('/api/staff/<int:staff_id>/breaks', methods=['GET','POST'])
@login_required
def staff_break_create_api(staff_id):
    Staff.query.get_or_404(staff_id)
    if request.method == 'GET':
        rows = StaffBreak.query.filter_by(staff_id=staff_id).order_by(StaffBreak.day_of_week, StaffBreak.start_time).all()
        return jsonify({'breaks': [{'id': b.id, 'day_of_week': b.day_of_week, 'start_time': b.start_time, 'end_time': b.end_time, 'is_active': b.is_active} for b in rows]})
    payload = request.get_json(silent=True) or {}
    try:
        day = int(payload.get('day_of_week'))
        start_time = payload.get('start_time')
        end_time = payload.get('end_time')
        datetime.strptime(start_time, '%H:%M')
        datetime.strptime(end_time, '%H:%M')
        if day not in range(7) or start_time >= end_time:
            raise ValueError
        row = StaffBreak(staff_id=staff_id, day_of_week=day, start_time=start_time, end_time=end_time, is_active=bool(payload.get('is_active', True)))
        db.session.add(row)
        db.session.commit()
        return jsonify({'ok': True, 'id': row.id})
    except (TypeError, ValueError):
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'Invalid staff break.'}), 400

@app.route('/invoices/<int:id>/tip', methods=['POST'])
@login_required
def update_invoice_tip(id):
    invoice = Invoice.query.get_or_404(id)
    if invoice.payment_status in {'Paid','Refunded'} or invoice_net_paid_amount(invoice) > 0:
        flash('Tip cannot be edited after payment. Create a new charge if needed.', 'warning')
        return redirect(url_for('view_invoice', id=id))
    try:
        tip = round(float(request.form.get('tip', 0) or 0), 2)
        if tip < 0:
            raise ValueError
        invoice.tip = tip
        recalculate_invoice(invoice)
        db.session.commit()
        flash('Tip updated.', 'success')
    except (ValueError, TypeError):
        db.session.rollback()
        flash('Enter a valid tip amount.', 'danger')
    return redirect(url_for('view_invoice', id=id))

@app.route('/invoices/<int:id>')
@login_required
def view_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    inventory_products = InventoryItem.query.filter_by(is_active=True).order_by(InventoryItem.name).all()
    salon_setting = SalonSetting.query.first()
    return render_template('invoice_detail.html', invoice=invoice, inventory_products=inventory_products, salon_setting=salon_setting)

@app.route('/invoices/pay/<int:id>', methods=['POST'])
@login_required
def mark_paid(id):
    invoice = Invoice.query.filter_by(id=id).with_for_update().first_or_404()
    if invoice.payment_status == 'Refunded':
        flash('A refunded invoice cannot receive another payment.', 'danger')
        return redirect(url_for('view_invoice', id=id))
    balance = invoice_balance(invoice)
    if balance <= 0:
        invoice.payment_status = 'Paid'
        award_loyalty_for_invoice(invoice)
        db.session.commit()
        return redirect(url_for('view_invoice', id=id))
    method = request.form.get('payment_method', 'Cash')
    allowed_methods = {'Cash', 'UPI', 'Card', 'Bank Transfer', 'Gift Card'}
    if method not in allowed_methods:
        flash('Choose a supported payment method.', 'danger')
        return redirect(url_for('view_invoice', id=id))
    try:
        amount = float(request.form.get('amount', balance))
        if amount <= 0 or amount > balance + 0.01:
            raise ValueError
    except (ValueError, TypeError):
        flash(f'Payment must be between ₹0.01 and ₹{balance:.2f}.', 'danger')
        return redirect(url_for('view_invoice', id=id))
    amount = round(min(amount, balance), 2)
    try:
        gift_card = None
        if method == 'Gift Card':
            code = request.form.get('gift_card_code', '').strip().upper()
            gift_card = GiftCard.query.filter_by(code=code, status='Active').with_for_update().first() if code else None
            if not gift_card:
                raise ValueError('Enter a valid active gift card code.')
            if gift_card.expires_at and gift_card.expires_at < date.today():
                gift_card.status = 'Expired'
                raise ValueError('This gift card has expired.')
            if amount > (gift_card.balance or 0) + 0.01:
                raise ValueError(f'Gift card balance is only ₹{(gift_card.balance or 0):.2f}.')
        db.session.add(InvoicePayment(invoice_id=invoice.id, amount=amount,
                                      payment_method=method, notes=request.form.get('notes') or (f'Gift card {gift_card.code}' if gift_card else None)))
        if gift_card:
            gift_card.balance = round(max((gift_card.balance or 0) - amount, 0), 2)
            if gift_card.balance <= 0.01:
                gift_card.balance = 0
                gift_card.status = 'Redeemed'
            db.session.add(GiftCardTransaction(gift_card_id=gift_card.id, transaction_type='Redeem', amount=amount, invoice_id=invoice.id, notes='Invoice payment'))
        invoice.payment_method = method
        db.session.flush()
        paid = invoice_paid_amount(invoice)
        invoice.payment_status = 'Paid' if paid >= invoice.total - 0.01 else 'Partial'
        if invoice.payment_status == 'Paid':
            award_loyalty_for_invoice(invoice)
        db.session.add(AuditLog(user_id=session.get('user_id'), action='Payment recorded', path=request.path, details=f'Invoice #{invoice.id} · ₹{amount:.2f}'))
        commit_or_rollback()
        flash(f'Payment of ₹{amount:.2f} recorded. Balance: ₹{invoice_balance(invoice):.2f}.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception:
        db.session.rollback()
        flash('Payment could not be saved. No changes were made.', 'danger')
    return redirect(url_for('view_invoice', id=id)

@app.route('/invoices/refund/<int:id>', methods=['POST'])
@admin_required
def refund_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    if invoice.payment_status == 'Refunded':
        flash('This invoice has already been fully refunded.', 'warning')
        return redirect(url_for('view_invoice', id=id))
    remaining = invoice_net_paid_amount(invoice)
    if remaining <= 0:
        flash('Only paid invoices can be refunded.', 'warning')
        return redirect(url_for('view_invoice', id=id))
    was_fully_paid = remaining >= invoice.total - 0.01
    try:
        amount = round(float(request.form.get('amount', remaining)), 2)
        if amount <= 0 or amount > remaining + 0.01:
            raise ValueError
    except (ValueError, TypeError):
        flash(f'Refund must be between ₹0.01 and ₹{remaining:.2f}.', 'danger')
        return redirect(url_for('view_invoice', id=id))
    method = request.form.get('refund_method', invoice.payment_method or 'Cash')
    reason = request.form.get('reason', '').strip()
    try:
        db.session.add(InvoiceRefund(invoice_id=invoice.id, amount=amount, refund_method=method, reason=reason))
        if invoice.customer_id:
            setting = SalonSetting.query.first()
            rate = setting.loyalty_rate if setting else 1
            points = int(round(amount * rate / 100))
            loyalty = CustomerLoyalty.query.filter_by(customer_id=invoice.customer_id).first()
            if loyalty and points:
                loyalty.points = max(0, loyalty.points - points)
                loyalty.lifetime_spend = max(0, round(loyalty.lifetime_spend - amount, 2))
                db.session.add(LoyaltyTransaction(customer_id=invoice.customer_id, points=-points,
                    transaction_type='Refund', reference=f'refund:{invoice.id}:{secrets.token_hex(8)}', amount=-amount))
        net_after_refund = round(remaining - amount, 2)
        if was_fully_paid and amount >= remaining - 0.01:
            # Only a full refund of a fully-paid invoice closes the invoice and
            # restores linked retail stock.
            for line in invoice.items:
                sale_line = InventorySaleLine.query.filter_by(invoice_item_id=line.id).first()
                if sale_line:
                    item = InventoryItem.query.get(sale_line.inventory_item_id)
                    if item:
                        item.stock_qty += sale_line.quantity
                        record_inventory_transaction(item, 'Return', sale_line.quantity, item.cost_price,
                            reference=f'refund:{invoice.id}:item:{line.id}', notes=f'Restored after invoice #{invoice.id} refund.')
            invoice.payment_status = 'Refunded'
        elif net_after_refund >= invoice.total - 0.01:
            invoice.payment_status = 'Paid'
        elif net_after_refund > 0:
            invoice.payment_status = 'Partial'
        else:
            invoice.payment_status = 'Pending'
        db.session.add(AuditLog(user_id=session.get('user_id'), action='Refund recorded', path=request.path, details=f'Invoice #{invoice.id} · ₹{amount:.2f}'))
        commit_or_rollback()
        flash(f'Refund of ₹{amount:.2f} recorded.', 'success')
    except Exception:
        db.session.rollback()
        flash('Refund could not be saved. No changes were made.', 'danger')
    return redirect(url_for('view_invoice', id=id))

# ==================== INVENTORY ====================

@app.route('/inventory')
@login_required
def inventory():
    items = InventoryItem.query.order_by(InventoryItem.name).all()
    low_stock = [i for i in items if i.is_active and i.stock_qty <= i.reorder_level]
    rows = []
    for item in items:
        last_purchase = InventoryPurchase.query.filter_by(
            inventory_item_id=item.id
        ).order_by(InventoryPurchase.purchase_date.desc(), InventoryPurchase.id.desc()).first()
        last_sale = InventorySale.query.filter_by(
            inventory_item_id=item.id
        ).order_by(InventorySale.created_at.desc()).first()
        supplier = last_purchase.supplier if last_purchase else None
        profit_per_item = max((item.sale_price or 0) - (item.cost_price or 0), 0)
        rows.append({
            'item': item,
            'stock_value': round((item.stock_qty or 0) * (item.cost_price or 0), 2),
            'profit_per_item': round(profit_per_item, 2),
            'potential_profit': round(profit_per_item * max(item.stock_qty or 0, 0), 2),
            'supplier': supplier,
            'last_purchase': last_purchase,
            'last_sale': last_sale,
        })
    potential_profit = round(sum(r['potential_profit'] for r in rows if r['item'].is_active), 2)
    return render_template('inventory.html', items=items, low_stock=low_stock, rows=rows,
                           potential_profit=potential_profit)

@app.route('/inventory/add', methods=['GET', 'POST'])
@login_required
def add_inventory():
    if request.method == 'POST':
        try:
            stock = float(request.form.get('stock_qty', 0))
            reorder = float(request.form.get('reorder_level', 5))
            cost = float(request.form.get('cost_price', 0))
            sale = float(request.form.get('sale_price', 0))
            if min(stock, reorder, cost, sale) < 0:
                raise ValueError
        except (ValueError, TypeError):
            flash('Enter valid non-negative stock and prices.', 'danger')
            return redirect(url_for('add_inventory'))
        item = InventoryItem(name=request.form['name'].strip(),
                             sku=request.form.get('sku','').strip() or None,
                             category=request.form.get('category'),
                             stock_qty=stock, reorder_level=reorder,
                             cost_price=cost, sale_price=sale, is_active=True)
        db.session.add(item)
        try:
            db.session.flush()
            if stock > 0:
                record_inventory_transaction(item, 'Purchase', stock, cost,
                                             reference=f'opening-stock:{item.id}',
                                             notes='Opening stock entered when product was created.')
            db.session.commit()
            flash('Inventory item added!', 'success')
        except Exception:
            db.session.rollback()
            flash('SKU already exists. Use a different SKU.', 'danger')
        return redirect(url_for('inventory'))
    return render_template('inventory_form.html', item=None)

@app.route('/inventory/adjust/<int:id>', methods=['POST'])
@login_required
def adjust_inventory(id):
    item = InventoryItem.query.filter_by(id=id).with_for_update().first_or_404()
    try:
        change = float(request.form['change'])
        new_qty = item.stock_qty + change
        if new_qty < 0:
            raise ValueError
    except (ValueError, TypeError):
        flash('Stock adjustment would create an invalid quantity.', 'danger')
        return redirect(url_for('inventory'))
    item.stock_qty = new_qty
    record_inventory_transaction(item, 'Adjustment', change, item.cost_price,
                                  reference=f'adjustment:{item.id}:{datetime.utcnow().isoformat()}')
    db.session.add(AuditLog(user_id=session.get('user_id'), action='Inventory adjusted', path=request.path, details=f'{item.name} · change {change:g}'))
    db.session.commit()
    flash(f'{item.name} stock updated to {item.stock_qty:g}.', 'success')
    return redirect(url_for('inventory'))

@app.route('/inventory/transactions')
@login_required
def inventory_transactions():
    item_id = request.args.get('item_id', type=int)
    tx_type = request.args.get('type', '').strip()
    query = InventoryTransaction.query
    if item_id:
        query = query.filter_by(inventory_item_id=item_id)
    if tx_type:
        query = query.filter_by(transaction_type=tx_type)
    transactions = query.order_by(InventoryTransaction.created_at.desc()).limit(300).all()
    items = InventoryItem.query.order_by(InventoryItem.name).all()
    return render_template('inventory_transactions.html', transactions=transactions, items=items,
                           selected_item=item_id, selected_type=tx_type)

@app.route('/supplier-intelligence')
@login_required
def supplier_intelligence():
    suppliers_list = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    rows=[]
    for supplier in suppliers_list:
        purchases=InventoryPurchase.query.filter_by(supplier_id=supplier.id).order_by(
            InventoryPurchase.purchase_date.desc(), InventoryPurchase.id.desc()).all()
        latest = purchases[0] if purchases else None
        previous = None
        changes=[]
        seen=set()
        for p in purchases:
            if p.inventory_item_id in seen:
                continue
            seen.add(p.inventory_item_id)
            prev=next((x for x in purchases[purchases.index(p)+1:] if x.inventory_item_id==p.inventory_item_id),None)
            if prev and prev.unit_cost:
                change=round((p.unit_cost-prev.unit_cost)/prev.unit_cost*100,1)
                if abs(change)>=1:
                    changes.append({'item':p.inventory_item.name if p.inventory_item else 'Product','change':change,'latest':p.unit_cost,'previous':prev.unit_cost})
        rows.append({
            'supplier':supplier,
            'purchase_count':len(purchases),
            'total_spend':round(sum(p.total_cost for p in purchases),2),
            'last_purchase':latest,
            'changes':changes[:8],
        })
    return render_template('supplier_intelligence.html', rows=rows)

@app.route('/suppliers')
@login_required
def suppliers():
    suppliers_list = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template('suppliers.html', suppliers=suppliers_list)

@app.route('/suppliers/add', methods=['GET', 'POST'])
@admin_required
def add_supplier():
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        if not name:
            flash('Supplier name is required.', 'danger')
            return redirect(url_for('add_supplier'))
        db.session.add(Supplier(name=name, phone=request.form.get('phone','').strip(),
                                 email=request.form.get('email','').strip(),
                                 address=request.form.get('address','').strip(),
                                 notes=request.form.get('notes','').strip()))
        db.session.commit()
        flash('Supplier added.', 'success')
        return redirect(url_for('suppliers'))
    return render_template('supplier_form.html', supplier=None)

@app.route('/suppliers/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_supplier(id):
    supplier = Supplier.query.get_or_404(id)
    if request.method == 'POST':
        supplier.name = request.form.get('name','').strip()
        supplier.phone = request.form.get('phone','').strip()
        supplier.email = request.form.get('email','').strip()
        supplier.address = request.form.get('address','').strip()
        supplier.notes = request.form.get('notes','').strip()
        if not supplier.name:
            flash('Supplier name is required.', 'danger')
            return redirect(url_for('edit_supplier', id=id))
        db.session.commit()
        flash('Supplier updated.', 'success')
        return redirect(url_for('suppliers'))
    return render_template('supplier_form.html', supplier=supplier)

@app.route('/purchases')
@login_required
def purchases():
    purchases_list = InventoryPurchase.query.order_by(InventoryPurchase.purchase_date.desc(),
                                                       InventoryPurchase.id.desc()).limit(300).all()
    return render_template('purchases.html', purchases=purchases_list)

@app.route('/purchases/add', methods=['GET', 'POST'])
@admin_required
def add_purchase():
    if request.method == 'POST':
        try:
            item = InventoryItem.query.filter_by(id=int(request.form['inventory_item_id'])).with_for_update().first_or_404()
            quantity = float(request.form.get('quantity', 0))
            unit_cost = float(request.form.get('unit_cost', 0))
            purchase_date = datetime.strptime(request.form.get('purchase_date',''), '%Y-%m-%d').date()
            if quantity <= 0 or unit_cost < 0:
                raise ValueError
        except (ValueError, TypeError):
            flash('Enter valid purchase details.', 'danger')
            return redirect(url_for('add_purchase'))
        supplier_id = request.form.get('supplier_id', type=int)
        total = round(quantity * unit_cost, 2)
        purchase = InventoryPurchase(supplier_id=supplier_id or None, inventory_item_id=item.id,
                                     quantity=quantity, unit_cost=unit_cost, total_cost=total,
                                     purchase_date=purchase_date,
                                     reference=request.form.get('reference','').strip(),
                                     notes=request.form.get('notes','').strip())
        item.stock_qty += quantity
        db.session.add(purchase)
        record_inventory_transaction(item, 'Purchase', quantity, unit_cost,
                                     reference=purchase.reference or f'purchase:{datetime.utcnow().isoformat()}',
                                     notes=purchase.notes)
        db.session.commit()
        flash(f'Purchase recorded. {item.name} stock increased by {quantity:g}.', 'success')
        return redirect(url_for('purchases'))
    items = InventoryItem.query.filter_by(is_active=True).order_by(InventoryItem.name).all()
    suppliers_list = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template('purchase_form.html', items=items, suppliers=suppliers_list,
                           today_iso=date.today().isoformat())


# ==================== POS INVOICE ITEMS ====================

@app.route('/invoices/<int:id>/items/add', methods=['POST'])
@login_required
def add_invoice_item(id):
    invoice = Invoice.query.get_or_404(id)
    if invoice.payment_status in ('Paid', 'Refunded'):
        flash('Paid or refunded invoices cannot be edited. Create a new invoice for additional charges.', 'warning')
        return redirect(url_for('view_invoice', id=id))
    try:
        description = request.form['description'].strip()
        quantity = float(request.form.get('quantity', 1))
        unit_price = float(request.form['unit_price'])
        if not description or quantity <= 0 or unit_price < 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        flash('Enter valid item details.', 'danger')
        return redirect(url_for('view_invoice', id=id))
    item = InvoiceItem(invoice_id=invoice.id, description=description,
                       quantity=quantity, unit_price=unit_price,
                       total=round(quantity * unit_price, 2))
    db.session.add(item)
    db.session.flush()
    subtotal = sum(i.total for i in invoice.items)
    invoice.amount = round(subtotal, 2)
    recalculate_invoice(invoice)
    db.session.commit()
    flash('Item added to invoice.', 'success')
    return redirect(url_for('view_invoice', id=id))

@app.route('/invoices/<int:id>/items/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_invoice_item(id, item_id):
    invoice = Invoice.query.get_or_404(id)
    if invoice.payment_status in ('Paid', 'Refunded') or invoice_net_paid_amount(invoice) > 0:
        flash('An invoice with payments cannot be edited. Refund the payment first if a correction is required.', 'warning')
        return redirect(url_for('view_invoice', id=id))
    item = InvoiceItem.query.filter_by(id=item_id, invoice_id=id).first_or_404()
    if len(invoice.items) <= 1:
        flash('An invoice must keep at least one item.', 'warning')
        return redirect(url_for('view_invoice', id=id))
    sale_line = InventorySaleLine.query.filter_by(invoice_item_id=item.id).first()
    if sale_line:
        inventory_item = InventoryItem.query.get(sale_line.inventory_item_id)
        if inventory_item:
            inventory_item.stock_qty += sale_line.quantity
            record_inventory_transaction(
                inventory_item, 'Return', sale_line.quantity, inventory_item.cost_price,
                reference=f'invoice-item-return:{item.id}',
                notes=f'Restored after removing invoice #{invoice.id} item.'
            )
        if sale_line.inventory_sale:
            db.session.delete(sale_line.inventory_sale)
        db.session.delete(sale_line)
    db.session.delete(item)
    db.session.flush()
    subtotal = sum(i.total for i in invoice.items)
    invoice.amount = round(subtotal, 2)
    recalculate_invoice(invoice)
    db.session.commit()
    flash('Invoice item removed.', 'info')
    return redirect(url_for('view_invoice', id=id))

# ==================== STAFF PERFORMANCE ====================

@app.route('/staff/performance')
@login_required
def staff_performance_overview():
    today = date.today()
    start_text = request.args.get('start', today.replace(day=1).isoformat())
    end_text = request.args.get('end', today.isoformat())
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
        if end < start:
            raise ValueError
    except ValueError:
        start, end = today.replace(day=1), today
        start_text, end_text = start.isoformat(), end.isoformat()

    rows = []
    for member in Staff.query.filter_by(is_active=True).order_by(Staff.name).all():
        appts = Appointment.query.filter(
            Appointment.staff_id == member.id,
            Appointment.appointment_date >= start,
            Appointment.appointment_date <= end
        ).all()
        completed = [a for a in appts if a.status == 'Completed']
        invoices = Invoice.query.join(Appointment, Invoice.appointment_id == Appointment.id).filter(
            Appointment.staff_id == member.id,
            Invoice.created_at >= datetime.combine(start, datetime.min.time()),
            Invoice.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time())
        ).all()
        revenue = round(sum(invoice_net_paid_amount(i) for i in invoices), 2)
        customers_served = len({a.customer_id for a in completed})
        repeat_customers = sum(
            1 for customer_id in {a.customer_id for a in completed}
            if Appointment.query.filter_by(customer_id=customer_id, status='Completed').count() >= 2
        )
        average_bill = round(revenue / len(completed), 2) if completed else 0
        commission_settings = StaffCommission.query.filter_by(staff_id=member.id).first()
        rate = commission_settings.commission_rate if commission_settings else 0
        commission = round(max(revenue, 0) * rate / 100, 2)
        attendance = StaffAttendance.query.filter(
            StaffAttendance.staff_id == member.id,
            StaffAttendance.attendance_date >= start,
            StaffAttendance.attendance_date <= end,
            StaffAttendance.status == 'Present'
        ).count()
        rows.append({
            'member': member,
            'customers_served': customers_served,
            'revenue': revenue,
            'services_completed': len(completed),
            'average_bill': average_bill,
            'commission': commission,
            'attendance': attendance,
            'no_shows': sum(1 for a in appts if a.status == 'No-Show'),
            'repeat_customers': repeat_customers
        })
    return render_template('staff_performance_overview.html', rows=rows, start=start_text, end=end_text)


@app.route('/staff/<int:id>/performance')
@login_required
def staff_performance(id):
    member = Staff.query.get_or_404(id)
    start_text = request.args.get('start', date.today().replace(day=1).isoformat())
    end_text = request.args.get('end', date.today().isoformat())
    try:
        start = datetime.strptime(start_text, '%Y-%m-%d').date()
        end = datetime.strptime(end_text, '%Y-%m-%d').date()
    except ValueError:
        start = date.today().replace(day=1)
        end = date.today()
        start_text, end_text = start.isoformat(), end.isoformat()

    appointments = Appointment.query.filter(
        Appointment.staff_id == id,
        Appointment.appointment_date >= start,
        Appointment.appointment_date <= end
    ).order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc()).all()

    completed = [a for a in appointments if a.status == 'Completed']
    staff_invoices = Invoice.query.join(Appointment, Invoice.appointment_id == Appointment.id).filter(
        Appointment.staff_id == id,
        func.date(Invoice.created_at) >= start,
        func.date(Invoice.created_at) <= end
    ).all()
    paid_revenue = round(sum(invoice_net_paid_amount(inv) for inv in staff_invoices), 2)
    settings = StaffCommission.query.filter_by(staff_id=id).first()
    rate = settings.commission_rate if settings else 0
    commission = round(sum(
        max(invoice_net_paid_amount(inv), 0) *
        ((inv.commission_rate if inv.commission_rate is not None else rate) / 100)
        for inv in staff_invoices
    ), 2)
    schedules = StaffSchedule.query.filter_by(staff_id=id).order_by(StaffSchedule.day_of_week).all()
    breaks = StaffBreak.query.filter_by(staff_id=id).order_by(StaffBreak.day_of_week, StaffBreak.start_time).all()
    return render_template('staff_performance.html', member=member, appointments=appointments,
                           completed_count=len(completed), paid_revenue=paid_revenue,
                           rate=rate, commission=commission, start=start_text, end=end_text, schedules=schedules, breaks=breaks)

@app.route('/staff/<int:id>/availability', methods=['POST'])
@admin_required
def update_staff_availability(id):
    member = Staff.query.get_or_404(id)
    try:
        day = int(request.form.get('day_of_week'))
        start_time = request.form.get('start_time', '09:00')
        end_time = request.form.get('end_time', '20:00')
        is_working = request.form.get('is_working') == 'on'
        datetime.strptime(start_time, '%H:%M')
        datetime.strptime(end_time, '%H:%M')
        if day not in range(7) or start_time >= end_time:
            raise ValueError
        row = StaffSchedule.query.filter_by(staff_id=member.id, day_of_week=day).first()
        if not row:
            row = StaffSchedule(staff_id=member.id, day_of_week=day)
            db.session.add(row)
        row.start_time = start_time
        row.end_time = end_time
        row.is_working = is_working
        db.session.commit()
        flash('Staff availability saved.', 'success')
    except (ValueError, TypeError):
        db.session.rollback()
        flash('Enter valid availability times.', 'danger')
    return redirect(url_for('staff_performance', id=id))

@app.route('/staff/<int:id>/break', methods=['POST'])
@admin_required
def add_staff_break(id):
    member = Staff.query.get_or_404(id)
    try:
        day = int(request.form.get('day_of_week'))
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        datetime.strptime(start_time, '%H:%M')
        datetime.strptime(end_time, '%H:%M')
        if day not in range(7) or start_time >= end_time:
            raise ValueError
        db.session.add(StaffBreak(staff_id=member.id, day_of_week=day, start_time=start_time, end_time=end_time, is_active=True))
        db.session.commit()
        flash('Staff break added.', 'success')
    except (ValueError, TypeError):
        db.session.rollback()
        flash('Enter a valid staff break.', 'danger')
    return redirect(url_for('staff_performance', id=id))

@app.route('/staff/<int:id>/commission', methods=['POST'])
@login_required
def update_staff_commission(id):
    member = Staff.query.get_or_404(id)
    try:
        rate = float(request.form.get('commission_rate', 0))
        if rate < 0 or rate > 100:
            raise ValueError
    except (ValueError, TypeError):
        flash('Commission rate must be between 0% and 100%.', 'danger')
        return redirect(url_for('staff_performance', id=id))
    settings = StaffCommission.query.filter_by(staff_id=member.id).first()
    if not settings:
        settings = StaffCommission(staff_id=member.id)
        db.session.add(settings)
    settings.commission_rate = rate
    settings.commission_type = 'Percentage'
    db.session.commit()
    flash('Commission settings updated.', 'success')
    return redirect(url_for('staff_performance', id=id))

# ==================== ATTENDANCE ====================
@app.route('/attendance')
@login_required
def attendance():
    selected = request.args.get('date', date.today().isoformat())
    try:
        attendance_date = datetime.strptime(selected, '%Y-%m-%d').date()
    except ValueError:
        attendance_date = date.today()
        selected = attendance_date.isoformat()
    staff_list = Staff.query.order_by(Staff.name).all()
    records = {r.staff_id: r for r in StaffAttendance.query.filter_by(attendance_date=attendance_date).all()}
    return render_template('attendance.html', staff_list=staff_list, records=records, selected=selected)

@app.route('/attendance/mark', methods=['POST'])
@login_required
def mark_attendance():
    try:
        staff_id = int(request.form['staff_id'])
        attendance_date = datetime.strptime(request.form['attendance_date'], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        flash('Invalid staff or date.', 'danger')
        return redirect(url_for('attendance'))
    Staff.query.get_or_404(staff_id)
    record = StaffAttendance.query.filter_by(staff_id=staff_id, attendance_date=attendance_date).first()
    if not record:
        record = StaffAttendance(staff_id=staff_id, attendance_date=attendance_date)
        db.session.add(record)
    record.status = request.form.get('status', 'Present')
    record.check_in = request.form.get('check_in') or None
    record.check_out = request.form.get('check_out') or None
    record.notes = request.form.get('notes') or None
    db.session.commit()
    flash('Attendance saved.', 'success')
    return redirect(url_for('attendance', date=attendance_date.isoformat()))

# ==================== REPORTS ====================

@app.route('/reports')
@login_required
def reports():
    today = date.today()
    start_text = request.args.get('start', today.replace(day=1).isoformat())
    end_text = request.args.get('end', today.isoformat())
    try:
        start = datetime.strptime(start_text, '%Y-%m-%d').date()
        end = datetime.strptime(end_text, '%Y-%m-%d').date()
        if end < start:
            raise ValueError
    except ValueError:
        start = today.replace(day=1)
        end = today
        start_text, end_text = start.isoformat(), end.isoformat()

    invoices = Invoice.query.filter(
        func.date(Invoice.created_at) >= start,
        func.date(Invoice.created_at) <= end
    ).all()
    paid = [invoice for invoice in invoices if invoice_net_paid_amount(invoice) > 0]
    pending = [invoice for invoice in invoices if invoice_balance(invoice) > 0]
    expenses_list = Expense.query.filter(Expense.expense_date >= start, Expense.expense_date <= end).all()
    appts = Appointment.query.filter(Appointment.appointment_date >= start, Appointment.appointment_date <= end).all()

    revenue = round(sum(invoice_net_paid_amount(i) for i in paid), 2)
    expenses_total = round(sum(e.amount for e in expenses_list), 2)
    profit = round(revenue - expenses_total, 2)
    completed = sum(1 for a in appts if a.status == 'Completed')
    no_show = sum(1 for a in appts if a.status == 'No-Show')
    cancelled = sum(1 for a in appts if a.status == 'Cancelled')

    service_counts = {}
    for a in appts:
        if a.status == 'Completed' and a.service:
            key = a.service.name
            service_counts[key] = service_counts.get(key, 0) + 1
    top_services = sorted(service_counts.items(), key=lambda x: (-x[1], x[0]))[:8]

    service_revenue = {}
    for inv in paid:
        if not inv.appointment or not inv.appointment.service:
            continue
        service_name = inv.appointment.service.name
        service_revenue[service_name] = service_revenue.get(service_name, 0) + invoice_net_paid_amount(inv)
    top_service_revenue = sorted(
        service_revenue.items(), key=lambda x: (-x[1], x[0])
    )[:8]

    expense_categories = {}
    for expense in expenses_list:
        expense_categories[expense.category] = expense_categories.get(expense.category, 0) + expense.amount
    expense_categories = sorted(
        ((name, round(amount, 2)) for name, amount in expense_categories.items()),
        key=lambda x: (-x[1], x[0])
    )

    staff_rows = []
    for member in Staff.query.order_by(Staff.name).all():
        member_appts = [a for a in appts if a.staff_id == member.id]
        member_paid = sum(
            invoice_net_paid_amount(inv) for inv in paid
            if inv.appointment and inv.appointment.staff_id == member.id
        )
        settings = StaffCommission.query.filter_by(staff_id=member.id).first()
        rate = settings.commission_rate if settings else 0
        member_invoices = [
            inv for inv in paid
            if inv.appointment and inv.appointment.staff_id == member.id
        ]
        commission = round(sum(
            max(invoice_net_paid_amount(inv), 0) *
            ((inv.commission_rate if inv.commission_rate is not None else rate) / 100)
            for inv in member_invoices
        ), 2)
        staff_rows.append({
            'member': member,
            'appointments': len(member_appts),
            'completed': sum(1 for a in member_appts if a.status == 'Completed'),
            'revenue': round(member_paid, 2),
            'rate': rate,
            'commission': commission
        })

    daily = {}
    cursor = start
    while cursor <= end:
        daily[cursor.isoformat()] = 0
        cursor += timedelta(days=1)
    for inv in paid:
        day_key = inv.created_at.date().isoformat()
        if day_key in daily:
            daily[day_key] += invoice_net_paid_amount(inv)
    daily_rows = [{'date': k, 'revenue': round(v, 2)} for k, v in daily.items()]

    return render_template('reports.html', start=start_text, end=end_text, revenue=revenue,
                           expenses_total=expenses_total, profit=profit, paid_count=len(paid),
                           pending_count=len(pending), completed=completed, no_show=no_show,
                           cancelled=cancelled, top_services=top_services,
                           top_service_revenue=top_service_revenue,
                           expense_categories=expense_categories,
                           staff_rows=staff_rows, daily_rows=daily_rows)

@app.route('/reports/export.csv')
@login_required
def export_report_csv():
    import csv
    from io import StringIO
    today = date.today()
    try:
        start = datetime.strptime(request.args.get('start', today.replace(day=1).isoformat()), '%Y-%m-%d').date()
        end = datetime.strptime(request.args.get('end', today.isoformat()), '%Y-%m-%d').date()
        if end < start:
            raise ValueError
    except ValueError:
        start, end = today.replace(day=1), today

    invoices = Invoice.query.filter(
        func.date(Invoice.created_at) >= start,
        func.date(Invoice.created_at) <= end
    ).all()
    paid = [invoice for invoice in invoices if invoice_net_paid_amount(invoice) > 0]
    expenses_list = Expense.query.filter(Expense.expense_date >= start, Expense.expense_date <= end).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Salon Pro Report', start.isoformat(), end.isoformat()])
    writer.writerow([])
    writer.writerow(['Collected Invoice ID', 'Date', 'Customer', 'Collected Amount', 'Payment Method'])
    for inv in paid:
        writer.writerow([inv.id, inv.created_at.strftime('%Y-%m-%d'), inv.customer.name if inv.customer else '',
                         f'{invoice_net_paid_amount(inv):.2f}', inv.payment_method or ''])
    writer.writerow([])
    writer.writerow(['Expense ID', 'Date', 'Title', 'Category', 'Amount'])
    for exp in expenses_list:
        writer.writerow([exp.id, exp.expense_date.isoformat(), exp.title, exp.category, f'{exp.amount:.2f}'])
    from flask import Response
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=salon-pro-report-{start.isoformat()}-to-{end.isoformat()}.csv'})

# ==================== LOYALTY ====================

@app.route('/loyalty')
@login_required
def loyalty():
    customers_list = Customer.query.order_by(Customer.name).all()
    rows = []
    for customer in customers_list:
        loyalty = CustomerLoyalty.query.filter_by(customer_id=customer.id).first()
        paid = sum(invoice_net_paid_amount(i) for i in Invoice.query.filter_by(customer_id=customer.id).all())
        spend = loyalty.lifetime_spend if loyalty else paid
        points = loyalty.points if loyalty else int(paid * (SalonSetting.query.first().loyalty_rate if SalonSetting.query.first() else 1) / 100)
        rows.append({'customer': customer, 'points': points, 'spend': round(spend,2)})
    setting = SalonSetting.query.first()
    reward_threshold = 1000
    reward_value = 500
    for row in rows:
        row['next_reward_points'] = max(reward_threshold - row['points'], 0)
        row['reward_value'] = reward_value
    rows.sort(key=lambda x: (-x['points'], x['customer'].name.lower()))
    return render_template('loyalty.html', rows=rows, reward_threshold=reward_threshold, reward_value=reward_value)

# ==================== PACKAGES & MEMBERSHIPS ====================

@app.route('/packages')
@login_required
def packages():
    packages_list = SalonPackage.query.filter_by(is_active=True).order_by(SalonPackage.name).all()
    rows = CustomerPackage.query.order_by(CustomerPackage.expires_at.asc()).limit(300).all()
    changed = False
    for row in rows:
        if row.status == 'Active' and row.expires_at < date.today():
            row.status = 'Expired'
            changed = True
    if changed:
        db.session.commit()
    month_start = date.today().replace(day=1)
    package_invoices = Invoice.query.filter(func.date(Invoice.created_at)>=month_start, Invoice.created_at <= datetime.now()).all()
    package_revenue = round(sum(invoice_net_paid_amount(i) for i in package_invoices if any('(' in (item.description or '') for item in i.items)), 2)
    expiry_soon = sum(1 for row in rows if row.status == 'Active' and row.expires_at <= date.today()+timedelta(days=30))
    active_memberships = sum(1 for row in rows if row.status == 'Active')
    return render_template('packages.html', packages=packages_list, customer_packages=rows[:100],
                           customers=Customer.query.order_by(Customer.name).all(),
                           package_revenue=package_revenue, expiry_soon=expiry_soon, active_memberships=active_memberships)

@app.route('/packages/add', methods=['GET', 'POST'])
@admin_required
def add_package():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            package_type = request.form.get('package_type', 'Package')
            price = float(request.form.get('price', 0) or 0)
            total_uses = int(request.form.get('total_uses', 1) or 1)
            validity_days = int(request.form.get('validity_days', 30) or 30)
            if not name or package_type not in {'Package', 'Membership'} or price < 0 or total_uses < 1 or validity_days < 1:
                raise ValueError
            db.session.add(SalonPackage(
                name=name,
                package_type=package_type,
                description=request.form.get('description', '').strip(),
                price=price,
                total_uses=total_uses,
                validity_days=validity_days,
                included_services=request.form.get('included_services', '').strip()
            ))
            db.session.commit()
            flash('Package / membership created.', 'success')
            return redirect(url_for('packages'))
        except (ValueError, TypeError):
            db.session.rollback()
            flash('Enter valid package details.', 'danger')
    return render_template('package_form.html')

@app.route('/packages/sell', methods=['POST'])
@login_required
def sell_package():
    try:
        customer = Customer.query.get_or_404(request.form.get('customer_id', type=int))
        package = SalonPackage.query.filter_by(id=request.form.get('package_id', type=int), is_active=True).first_or_404()
        payment_method = request.form.get('payment_method', 'Cash')
        purchased_at = datetime.utcnow()
        expires = purchased_at.date() + timedelta(days=package.validity_days or 30)
        row = CustomerPackage(
            customer_id=customer.id, package_id=package.id, purchased_at=purchased_at,
            expires_at=expires, uses_total=package.total_uses or 1, uses_used=0,
            prepaid_balance=package.price or 0, status='Active'
        )
        db.session.add(row)
        db.session.flush()
        invoice = Invoice(
            appointment_id=None, customer_id=customer.id, amount=package.price or 0,
            discount=0, tax=0, tip=0, total=package.price or 0,
            payment_status='Pending', payment_method=payment_method
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(
            invoice_id=invoice.id, description=f'{package.name} ({package.package_type})',
            quantity=1, unit_price=package.price or 0, total=package.price or 0
        ))
        db.session.add(InvoicePayment(
            invoice_id=invoice.id, amount=package.price or 0,
            payment_method=payment_method, notes='Package / membership purchase'
        ))
        invoice.payment_status = 'Paid'
        db.session.commit()
        award_loyalty_for_invoice(invoice)
        db.session.commit()
        flash(f'{package.name} sold to {customer.name}. Invoice #{invoice.id} is paid.', 'success')
    except Exception:
        db.session.rollback()
        flash('Package could not be assigned.', 'danger')
    return redirect(url_for('packages'))

@app.route('/packages/use/<int:id>', methods=['POST'])
@login_required
def use_package(id):
    row = CustomerPackage.query.get_or_404(id)
    if row.expires_at < date.today():
        row.status = 'Expired'
    elif row.status != 'Active':
        flash('This package is not active.', 'warning')
        return redirect(url_for('packages'))
    elif row.uses_used >= row.uses_total:
        row.status = 'Completed'
    else:
        row.uses_used += 1
        per_use = (row.package.price or 0) / max(row.uses_total or 1, 1)
        row.prepaid_balance = max(0, round((row.prepaid_balance or 0) - per_use, 2))
        if row.uses_used >= row.uses_total:
            row.status = 'Completed'
    db.session.commit()
    flash('Package usage recorded.', 'success')
    return redirect(url_for('packages'))


# ==================== REMINDERS ====================

@app.route('/reminders')
@login_required
def reminders():
    today = date.today()
    setting = SalonSetting.query.first()
    days = setting.reminder_days if setting else 1
    until = today + timedelta(days=max(1, min(days, 30)))
    upcoming = Appointment.query.filter(
        Appointment.appointment_date >= today,
        Appointment.appointment_date <= until,
        Appointment.status.in_(list(ACTIVE_APPOINTMENT_STATUSES))
    ).order_by(Appointment.appointment_date, Appointment.appointment_time).all()

    birthday_reminders = []
    anniversary_reminders = []
    retention_due = []
    retention_at_risk = []
    package_expiry = []
    special_until = today + timedelta(days=30)

    for customer in Customer.query.order_by(Customer.name).all():
        metrics = _customer_metrics(customer.id)
        if customer.date_of_birth:
            next_birthday = upcoming_annual_date(customer.date_of_birth, today)
            if next_birthday <= special_until:
                birthday_reminders.append({'customer': customer, 'date': next_birthday})
        if customer.anniversary_date:
            next_anniversary = upcoming_annual_date(customer.anniversary_date, today)
            if next_anniversary <= special_until:
                anniversary_reminders.append({'customer': customer, 'date': next_anniversary})

        for customer_package in CustomerPackage.query.filter_by(customer_id=customer.id, status='Active').all():
            if customer_package.expires_at >= today and customer_package.expires_at <= special_until:
                package_expiry.append({'customer': customer, 'package': customer_package})

        days_since = metrics['days_since_visit']
        last_service = metrics['last_visit'].service if metrics['last_visit'] else None
        low_days, high_days = service_retention_window(last_service, metrics['avg_visit_interval_days'])
        if metrics['visits'] > 0 and days_since is not None:
            if days_since >= high_days:
                retention_at_risk.append({'customer': customer, 'metrics': metrics, 'retention_min_days': low_days, 'retention_max_days': high_days})
            elif days_since >= low_days:
                retention_due.append({'customer': customer, 'metrics': metrics, 'retention_min_days': low_days, 'retention_max_days': high_days})

    birthday_reminders.sort(key=lambda row: (row['date'], row['customer'].name.lower()))
    anniversary_reminders.sort(key=lambda row: (row['date'], row['customer'].name.lower()))
    retention_due.sort(key=lambda row: (-(row['metrics']['days_since_visit'] or 0), row['customer'].name.lower()))
    retention_at_risk.sort(key=lambda row: (-(row['metrics']['days_since_visit'] or 0), row['customer'].name.lower()))

    return render_template(
        'reminders.html',
        upcoming=upcoming,
        days=days,
        birthday_reminders=birthday_reminders,
        anniversary_reminders=anniversary_reminders,
        retention_due=retention_due,
        retention_at_risk=retention_at_risk,
        package_expiry=package_expiry
    )

# ==================== INVENTORY SALES ====================

@app.route('/invoices/<int:id>/inventory-sale', methods=['POST'])
@login_required
def add_inventory_sale(id):
    invoice = Invoice.query.get_or_404(id)
    if invoice.payment_status in ('Paid', 'Refunded') or invoice_net_paid_amount(invoice) > 0:
        flash('An invoice with payments cannot receive new products. Create a new invoice for additional charges.', 'warning')
        return redirect(url_for('view_invoice', id=id))
    try:
        item_id = int(request.form['inventory_item_id'])
        quantity = float(request.form['quantity'])
        if quantity <= 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        flash('Enter a valid product and quantity.', 'danger')
        return redirect(url_for('view_invoice', id=id))
    item = InventoryItem.query.filter_by(id=item_id).with_for_update().first_or_404()
    if not item.is_active or item.stock_qty < quantity:
        flash(f'Not enough stock for {item.name}. Available: {item.stock_qty:g}.', 'danger')
        return redirect(url_for('view_invoice', id=id))
    sale = InventorySale(invoice_id=invoice.id, inventory_item_id=item.id,
                         quantity=quantity, unit_price=item.sale_price)
    db.session.add(sale)
    item.stock_qty = round(item.stock_qty - quantity, 3)
    line = InvoiceItem(invoice_id=invoice.id, description=item.name,
                       quantity=quantity, unit_price=item.sale_price,
                       total=round(quantity * item.sale_price, 2))
    db.session.add(line)
    db.session.flush()
    db.session.add(InventorySaleLine(
        inventory_sale_id=sale.id,
        invoice_item_id=line.id,
        inventory_item_id=item.id,
        quantity=quantity,
        unit_price=item.sale_price
    ))
    record_inventory_transaction(
        item, 'Sale', quantity, item.cost_price,
        reference=f'invoice:{invoice.id}:item:{line.id}',
        notes=f'Product sold on invoice #{invoice.id}.'
    )
    subtotal = sum(i.total for i in invoice.items)
    invoice.amount = round(subtotal, 2)
    recalculate_invoice(invoice)
    db.session.commit()
    flash(f'{item.name} added and {quantity:g} stock deducted.', 'success')
    return redirect(url_for('view_invoice', id=id))


DEFAULT_WHATSAPP_TEMPLATES = {
    'appointment': ('Appointment reminder', 'Hello {{name}}, your {{service}} appointment is tomorrow at {{time}} at {{salon_name}}.'),
    'confirmation': ('Appointment confirmation', 'Hello {{name}}, please confirm your {{service}} appointment on {{date}} at {{time}}.'),
    'cancellation': ('Cancellation', 'Hello {{name}}, your {{service}} appointment on {{date}} at {{time}} has been cancelled. Please contact {{salon_name}} to rebook.'),
    'birthday': ('Birthday', 'Happy Birthday {{name}}! 🎂 We would love to celebrate with you at {{salon_name}}.'),
    'return': ('Return reminder', 'Hello {{name}}, it has been {{days_since}} days since your last visit. We would love to see you again at {{salon_name}}.'),
    'payment': ('Payment receipt', 'Hello {{name}}, your payment has been received. Thank you for visiting {{salon_name}}.'),
    'package_expiry': ('Package expiry', 'Hello {{name}}, your {{package}} expires on {{expiry}}. Contact {{salon_name}} if you would like to renew.'),
    'waitlist': ('Waitlist opening', 'Hello {{name}}, a {{service}} slot has opened at {{date}} {{time}} at {{salon_name}}. Reply to confirm if you would like it.')
}

def service_retention_window(service, fallback_interval=None):
    if service:
        low = int(service.retention_min_days or 30)
        high = int(service.retention_max_days or max(low, 45))
        return low, max(high, low)
    interval = int(fallback_interval or 30)
    return max(14, int(interval * 0.8)), max(30, int(interval * 1.4))

def customer_next_best_action(customer, metrics):
    balance = metrics.get('outstanding_balance', 0)
    if balance > 0:
        return {'label': f"Collect ₹{balance:,.0f} outstanding", 'type': 'payment'}
    if metrics.get('next_visit'):
        appt = metrics['next_visit']
        return {'label': f"Prepare for {appt.appointment_date.strftime('%d %b')} appointment", 'type': 'appointment'}
    if not metrics.get('visits'):
        return {'label': 'Invite for first visit', 'type': 'new'}
    days_since = metrics.get('days_since_visit')
    service = metrics['last_visit'].service if metrics.get('last_visit') else None
    low, high = service_retention_window(service, metrics.get('avg_visit_interval_days'))
    if days_since is not None and days_since >= high:
        return {'label': f"Send return reminder — {days_since} days since last visit", 'type': 'return'}
    if days_since is not None and days_since >= low:
        return {'label': f"Customer is due — usual window {low}–{high} days", 'type': 'return'}
    return {'label': 'Keep relationship warm', 'type': 'nurture'}

def seed_default_whatsapp_templates():
    changed = False
    for key, values in DEFAULT_WHATSAPP_TEMPLATES.items():
        row = WhatsAppTemplate.query.filter_by(key=key).first()
        if not row:
            db.session.add(WhatsAppTemplate(key=key, name=values[0], category=key, body=values[1]))
            changed = True
    if changed:
        db.session.commit()

def render_whatsapp_template(key, context):
    row = WhatsAppTemplate.query.filter_by(key=key, is_active=True).first()
    body = row.body if row else DEFAULT_WHATSAPP_TEMPLATES.get(key, ('', ''))[1]
    for name, value in context.items():
        body = body.replace('{{' + name + '}}', str(value or ''))
    return body


@app.route('/insights')
@login_required
def insights():
    today=date.today(); start=today.replace(day=1); prev_end=start-timedelta(days=1); prev_start=prev_end.replace(day=1)
    invoices=Invoice.query.filter(func.date(Invoice.created_at)>=start,func.date(Invoice.created_at)<=today).all()
    prev=Invoice.query.filter(func.date(Invoice.created_at)>=prev_start,func.date(Invoice.created_at)<=prev_end).all()
    revenue=round(sum(invoice_net_paid_amount(i) for i in invoices),2); previous_revenue=round(sum(invoice_net_paid_amount(i) for i in prev),2)
    expenses=round(sum(e.amount for e in Expense.query.filter(Expense.expense_date>=start,Expense.expense_date<=today).all()),2)
    metrics=[_customer_metrics(c.id) for c in Customer.query.all()]
    service_revenue={}
    for inv in invoices:
        if inv.appointment and inv.appointment.service:
            service_revenue[inv.appointment.service.name]=service_revenue.get(inv.appointment.service.name,0)+invoice_net_paid_amount(inv)
    bookings={}
    for appt in Appointment.query.filter(Appointment.appointment_date>=start,Appointment.appointment_date<=today,Appointment.status=='Completed').all():
        if appt.service: bookings[appt.service.name]=bookings.get(appt.service.name,0)+1
    cutoff=datetime.utcnow()-timedelta(days=90); inventory_rows=[]
    for item in InventoryItem.query.filter_by(is_active=True).all():
        sold=sum(tx.quantity for tx in InventoryTransaction.query.filter_by(inventory_item_id=item.id,transaction_type='Sale').filter(InventoryTransaction.created_at>=cutoff).all())
        weekly=sold/13; days_left=(item.stock_qty/weekly*7) if weekly>0 else None
        recommended=max(float(item.reorder_level or 0)*2,weekly*4) if weekly>0 else float(item.reorder_level or 0)
        if item.stock_qty <= item.reorder_level or (days_left is not None and days_left<=14):
            inventory_rows.append({'item':item,'weekly_usage':round(weekly,2),'days_left':round(days_left,1) if days_left is not None else None,'recommended_qty':round(recommended,0)})
    return render_template('insights.html',
        revenue=revenue,previous_revenue=previous_revenue,expenses=expenses,profit=round(revenue-expenses,2),
        growth=round((revenue-previous_revenue)/previous_revenue*100,1) if previous_revenue else None,
        new_customers=sum(1 for c in Customer.query.all() if c.created_at and c.created_at.date()>=start),
        returning=sum(1 for m in metrics if m['visits']>=2),vip=sum(1 for m in metrics if m['lifetime_spend']>=25000),
        at_risk=sum(1 for m in metrics if m['days_since_visit'] is not None and m['days_since_visit']>=60),
        lost=sum(1 for m in metrics if m['days_since_visit'] is not None and m['days_since_visit']>=120),
        service_revenue=sorted(service_revenue.items(),key=lambda x:(-x[1],x[0]))[:8],
        booking_rows=sorted(bookings.items(),key=lambda x:(-x[1],x[0]))[:8],fast_inventory=inventory_rows[:12])

@app.route('/assistant', methods=['GET','POST'])
@login_required
def assistant():
    question=''; answer=None; facts=[]
    if request.method=='POST':
        question=request.form.get('question','').strip(); q=question.lower(); today=date.today()
        if any(k in q for k in ['today revenue','today sales','today collection']):
            invs=Invoice.query.filter(func.date(Invoice.created_at)==today).all(); answer=f"Today collected ₹{sum(invoice_net_paid_amount(i) for i in invs):,.2f}."
        elif 'month' in q and any(k in q for k in ['made','revenue','sales','collection']):
            start=today.replace(day=1); invs=Invoice.query.filter(func.date(Invoice.created_at)>=start,func.date(Invoice.created_at)<=today).all(); answer=f"This month collected ₹{sum(invoice_net_paid_amount(i) for i in invs):,.2f}."
        elif 'outstanding' in q or 'collect' in q:
            invs=Invoice.query.filter(Invoice.payment_status.in_(['Pending','Partial'])).all(); answer=f"₹{sum(invoice_balance(i) for i in invs):,.2f} is outstanding across {len([i for i in invs if invoice_balance(i)>0])} invoices."
        elif 'low stock' in q or 'running low' in q or 'reorder' in q:
            low=InventoryItem.query.filter(InventoryItem.is_active==True,InventoryItem.stock_qty<=InventoryItem.reorder_level).all(); answer=f"{len(low)} products need attention." if low else "No products are currently at or below reorder level."; facts=[f"{i.name}: {i.stock_qty:g} in stock" for i in low[:8]]
        elif 'top customer' in q or 'best customer' in q:
            rows=[(c,_customer_metrics(c.id)) for c in Customer.query.all()]; rows.sort(key=lambda x:-x[1]['lifetime_spend']); answer=f"{rows[0][0].name} has the highest lifetime spend at ₹{rows[0][1]['lifetime_spend']:,.2f}." if rows else "There are no customers yet."; facts=[f"{c.name}: ₹{m['lifetime_spend']:,.0f} · {m['visits']} visits" for c,m in rows[:5]]
        elif 'not visited' in q or 'overdue' in q or 'recently' in q:
            rows=[] 
            for c in Customer.query.all():
                m=_customer_metrics(c.id)
                if m['days_since_visit'] is not None and m['days_since_visit']>=60: rows.append((c,m))
            rows.sort(key=lambda x:-x[1]['days_since_visit']); answer=f"{len(rows)} customers have not visited for 60+ days."; facts=[f"{c.name}: {m['days_since_visit']} days since last visit" for c,m in rows[:8]]
        elif 'focus' in q or 'should i do' in q or 'next' in q:
            low=InventoryItem.query.filter(InventoryItem.is_active==True,InventoryItem.stock_qty<=InventoryItem.reorder_level).count(); overdue=sum(1 for c in Customer.query.all() if ((_customer_metrics(c.id)['days_since_visit'] or 0)>=60)); open_invoices=[i for i in Invoice.query.filter(Invoice.payment_status.in_(['Pending','Partial'])).all() if invoice_balance(i)>0]
            answer='Start with the highest-value items on the Command Center.'; facts=[f"{overdue} customers need reactivation",f"{low} products are low stock",f"₹{sum(invoice_balance(i) for i in open_invoices):,.0f} remains to collect"]
        else:
            answer="I can answer revenue, outstanding payments, customers, visits, low stock and today's priorities from Salon Pro's database."
    return render_template('assistant.html',question=question,answer=answer,facts=facts)

@app.route('/whatsapp/templates', methods=['GET','POST'])
@login_required
@admin_required
def whatsapp_templates():
    seed_default_whatsapp_templates()
    if request.method=='POST':
        for row in WhatsAppTemplate.query.order_by(WhatsAppTemplate.id).all():
            row.name=request.form.get(f'name_{row.id}',row.name).strip() or row.name
            row.body=request.form.get(f'body_{row.id}',row.body).strip() or row.body
            row.is_active=request.form.get(f'active_{row.id}')=='1'
        db.session.commit(); flash('WhatsApp templates saved.','success'); return redirect(url_for('whatsapp_templates'))
    return render_template('whatsapp_templates.html',templates=WhatsAppTemplate.query.order_by(WhatsAppTemplate.id).all())

@app.route('/whatsapp/send/<int:customer_id>/<key>')
@login_required
def whatsapp_send(customer_id,key):
    customer=Customer.query.get_or_404(customer_id); metrics=_customer_metrics(customer.id); setting=SalonSetting.query.first()
    service=(metrics['next_visit'].service if metrics.get('next_visit') else (metrics['last_visit'].service if metrics.get('last_visit') else None))
    expiring = CustomerPackage.query.filter_by(customer_id=customer.id, status='Active').order_by(CustomerPackage.expires_at.asc()).first()
    context={'name':customer.name,'service':service.name if service else metrics.get('favorite_service') or 'service',
             'date':metrics['next_visit'].appointment_date.strftime('%d %b %Y') if metrics.get('next_visit') else date.today().strftime('%d %b %Y'),
             'time':metrics['next_visit'].appointment_time if metrics.get('next_visit') else '',
             'days_since':metrics.get('days_since_visit') or 0,'amount':metrics.get('paid_revenue') or 0,
             'balance':metrics.get('outstanding_balance') or 0,
             'package':expiring.package.name if expiring and expiring.package else 'package',
             'expiry':expiring.expires_at.strftime('%d %b %Y') if expiring else '',
             'salon_name':setting.salon_name if setting else 'Salon Pro'}
    message=render_whatsapp_template(key,context); phone=''.join(ch for ch in (customer.phone or '') if ch.isdigit())
    return redirect(f"https://wa.me/{phone}?text={quote(message)}")

@app.route('/gift-cards', methods=['GET','POST'])
@login_required
def gift_cards():
    if request.method=='POST':
        try:
            amount=float(request.form.get('amount',0)); customer_id=request.form.get('customer_id',type=int)
            if amount<=0 or not customer_id: raise ValueError
            expiry_raw=request.form.get('expires_at','').strip(); expiry=date.fromisoformat(expiry_raw) if expiry_raw else None
            code='SPGC-'+secrets.token_hex(4).upper()
            while GiftCard.query.filter_by(code=code).first(): code='SPGC-'+secrets.token_hex(4).upper()
            card=GiftCard(code=code,purchaser_customer_id=customer_id,recipient_name=request.form.get('recipient_name','').strip() or None,original_amount=amount,balance=amount,expires_at=expiry)
            db.session.add(card); db.session.flush(); db.session.add(GiftCardTransaction(gift_card_id=card.id,transaction_type='Issued',amount=amount,notes='Gift card created')); db.session.commit()
            flash(f'Gift card {code} created with ₹{amount:,.0f}.','success')
        except (ValueError,TypeError): db.session.rollback(); flash('Enter a valid customer, amount and expiry.','danger')
        return redirect(url_for('gift_cards'))
    return render_template('gift_cards.html',cards=GiftCard.query.order_by(GiftCard.created_at.desc()).limit(200).all(),customers=Customer.query.order_by(Customer.name).all())

@app.route('/gift-cards/redeem/<int:id>', methods=['POST'])
@login_required
def redeem_gift_card(id):
    card=GiftCard.query.get_or_404(id)
    try:
        amount=round(float(request.form.get('amount',0)),2)
        if amount<=0 or amount>card.balance+0.01 or (card.expires_at and card.expires_at<date.today()): raise ValueError
        card.balance=round(card.balance-amount,2); card.status='Redeemed' if card.balance<=0.01 else 'Active'
        db.session.add(GiftCardTransaction(gift_card_id=card.id,transaction_type='Redeemed',amount=amount,notes=request.form.get('notes','').strip())); db.session.commit()
        flash(f'₹{amount:,.2f} redeemed from {card.code}.','success')
    except (ValueError,TypeError): db.session.rollback(); flash('Invalid gift card redemption.','danger')
    return redirect(url_for('gift_cards'))

@app.route('/audit-log')
@login_required
@admin_required
def audit_log():
    return render_template('audit_log.html',rows=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(300).all())

# ==================== SALON SETTINGS ====================

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    setting = SalonSetting.query.first()
    if not setting:
        setting = SalonSetting()
        db.session.add(setting)
        db.session.commit()

    if request.method == 'POST':
        setting.salon_name = request.form.get('salon_name', 'Salon Pro').strip() or 'Salon Pro'
        setting.phone = request.form.get('phone', '').strip()
        setting.address = request.form.get('address', '').strip()
        setting.invoice_prefix = request.form.get('invoice_prefix', 'SP').strip()[:20] or 'SP'
        setting.gst_number = request.form.get('gst_number', '').strip()[:30] or None
        try:
            upload = request.files.get('logo_file')
            if upload and upload.filename:
                raw = upload.read()
                if len(raw) > 512 * 1024:
                    raise ValueError('Logo must be 512 KB or smaller.')
                mime = (upload.mimetype or '').lower()
                if mime not in {'image/png','image/jpeg','image/webp'}:
                    raise ValueError('Logo must be PNG, JPG or WEBP.')
                setting.logo_data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            elif request.form.get('remove_logo') == '1':
                setting.logo_data_url = None
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return redirect(url_for('settings'))
        try:
            setting.tax_rate = max(0, min(100, float(request.form.get('tax_rate', 5))))
            setting.loyalty_rate = max(0, min(100, float(request.form.get('loyalty_rate', 1))))
            setting.reminder_days = max(1, min(30, int(request.form.get('reminder_days', 1))))
        except (ValueError, TypeError):
            flash('Enter valid numeric settings.', 'danger')
            hours = {h.day_of_week: h for h in SalonHours.query.all()}
            closures = SalonClosure.query.order_by(SalonClosure.closure_date).all()
            google_identity = GoogleIdentity.query.filter_by(user_id=session['user_id']).first()
            return render_template('settings.html', setting=setting, hours=hours, closures=closures, google_identity=google_identity)

        # Save the seven-day business-hours schedule.
        for day in range(7):
            hour = SalonHours.query.filter_by(day_of_week=day).first()
            if not hour:
                hour = SalonHours(day_of_week=day)
                db.session.add(hour)
            hour.open_time = request.form.get(f'open_{day}', '09:00')
            hour.close_time = request.form.get(f'close_{day}', '20:00')
            try:
                open_t = datetime.strptime(hour.open_time, '%H:%M').time()
                close_t = datetime.strptime(hour.close_time, '%H:%M').time()
            except ValueError:
                raise ValueError
            if not hour.is_closed and open_t >= close_t:
                raise ValueError
            hour.is_closed = request.form.get(f'closed_{day}') == '1'

        # Add/update a closure date when supplied.
        closure_value = request.form.get('closure_date', '').strip()
        if closure_value:
            try:
                closure_date = date.fromisoformat(closure_value)
                closure = SalonClosure.query.filter_by(closure_date=closure_date).first()
                if not closure:
                    closure = SalonClosure(closure_date=closure_date)
                    db.session.add(closure)
                closure.reason = request.form.get('closure_reason', '').strip()[:200] or None
            except ValueError:
                flash('Enter a valid closure date.', 'danger')
                hours = {h.day_of_week: h for h in SalonHours.query.all()}
                closures = SalonClosure.query.order_by(SalonClosure.closure_date).all()
                google_identity = GoogleIdentity.query.filter_by(user_id=session['user_id']).first()
                return render_template('settings.html', setting=setting, hours=hours, closures=closures, google_identity=google_identity)

        db.session.commit()
        flash('Salon settings and business hours saved.', 'success')
        return redirect(url_for('settings'))

    hours = {h.day_of_week: h for h in SalonHours.query.all()}
    closures = SalonClosure.query.order_by(SalonClosure.closure_date).all()
    google_identity = GoogleIdentity.query.filter_by(user_id=session['user_id']).first()
    return render_template('settings.html', setting=setting, hours=hours, closures=closures, google_identity=google_identity)

@app.route('/account/password', methods=['GET', 'POST'])
@login_required
def change_password():
    user = User.query.get_or_404(session['user_id'])
    if request.method == 'POST':
        current = request.form.get('current_password','')
        new = request.form.get('new_password','')
        confirm = request.form.get('confirm_password','')
        if not check_password_hash(user.password_hash, current):
            flash('Current password is incorrect.', 'danger')
        elif len(new) < 8:
            flash('New password must be at least 8 characters.', 'danger')
        elif new != confirm:
            flash('New passwords do not match.', 'danger')
        else:
            user.password_hash = generate_password_hash(new)
            db.session.commit()
            flash('Password changed successfully.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('change_password.html')

# ==================== INIT DB ====================

def init_db():
    with app.app_context():
        db.create_all()
        # Backfill line items for invoices created by older versions.
        for inv in Invoice.query.all():
            if not inv.items and inv.appointment and inv.appointment.service:
                svc = inv.appointment.service
                db.session.add(InvoiceItem(invoice_id=inv.id, description=svc.name,
                                           quantity=1, unit_price=svc.price,
                                           total=svc.price))
        # Ensure the application always has a complete seven-day schedule. This
        # also repairs existing installations that predate SalonHours initialization.
        for day in range(7):
            if not SalonHours.query.filter_by(day_of_week=day).first():
                db.session.add(SalonHours(day_of_week=day, open_time='09:00', close_time='20:00', is_closed=False))
        db.session.commit()
        # Create default admin if not exists
        if not User.query.filter_by(username='admin').first():
            admin_password = os.environ.get('SALON_PRO_ADMIN_PASSWORD')
            if not admin_password:
                if os.environ.get('FLASK_ENV') == 'production':
                    raise RuntimeError(
                        'SALON_PRO_ADMIN_PASSWORD must be set before initializing a production database.'
                    )
                admin_password = 'admin123'
            if len(admin_password) < 12:
                raise RuntimeError('SALON_PRO_ADMIN_PASSWORD must be at least 12 characters.')
            admin = User(
                username='admin',
                password_hash=generate_password_hash(admin_password),
                role='admin'
            )
            db.session.add(admin)
            
            # Sample services
            sample_services = [
                Service(name='Haircut (Men)', duration_minutes=30, price=200, category='Hair'),
                Service(name='Haircut (Women)', duration_minutes=45, price=350, category='Hair'),
                Service(name='Hair Coloring', duration_minutes=90, price=1500, category='Hair'),
                Service(name='Facial', duration_minutes=60, price=800, category='Skin'),
                Service(name='Manicure', duration_minutes=40, price=400, category='Nails'),
                Service(name='Pedicure', duration_minutes=50, price=500, category='Nails'),
                Service(name='Bridal Makeup', duration_minutes=120, price=5000, category='Makeup'),
            ]
            db.session.add_all(sample_services)
            
            # Sample staff
            sample_staff = [
                Staff(name='Priya Sharma', phone='9876543210', specialty='Hair Stylist'),
                Staff(name='Rahul Verma', phone='9876543211', specialty='Barber & Color'),
                Staff(name='Anjali Patel', phone='9876543212', specialty='Makeup Artist'),
                Staff(name='Sneha Gupta', phone='9876543213', specialty='Skin & Nails'),
            ]
            db.session.add_all(sample_staff)
            
            db.session.commit()
            print("Database initialized with default admin (admin / admin123) and sample data.")

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)