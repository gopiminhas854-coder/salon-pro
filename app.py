from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta, timezone
from functools import wraps
import os
import secrets
import io
import json
import gzip
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
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///salon.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
app.config['SESSION_COOKIE_PATH'] = '/'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ==================== MODELS ====================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='admin')

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointments = db.relationship('Appointment', backref='customer', lazy=True)

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    duration_minutes = db.Column(db.Integer, default=30)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50))
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
    appointment_time = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), default='Scheduled')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    service = db.relationship('Service')

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
    total = db.Column(db.Float, nullable=False)
    payment_status = db.Column(db.String(20), default='Pending')
    payment_method = db.Column(db.String(30))
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
    created_at = db.Column(datetime, default=datetime.utcnow)
    invoice = db.relationship('Invoice', backref='payments')

class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    description = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Float, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    invoice = db.relationship('Invoice', backref=db.backref('items', lazy=True, cascade='all, delete-orphan'))

# ==================== AUTH ====================

def current_user():
    user_id = session.get('user_id')
    return User.query.get(user_id) if user_id else None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Admin access is required for this action.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
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
    return round(max(invoice.total - invoice_net_paid_amount(invoice), 0), 2)

def csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token

@app.context_processor
def template_helpers():
    return {'invoice_paid_amount': invoice_paid_amount, 'invoice_refunded_amount': invoice_refunded_amount, 'invoice_balance': invoice_balance, 'csrf_token': csrf_token}


def recalculate_invoice(invoice):
    subtotal = round(sum(i.total for i in invoice.items), 2)
    invoice.amount = subtotal
    taxable = max(invoice.amount - (invoice.discount or 0), 0)
    invoice.tax = round(taxable * get_tax_rate() / 100, 2)
    invoice.total = round(taxable + invoice.tax, 2)

ADMIN_ONLY_ENDPOINTS = {
    'settings', 'download_backup',
    'add_staff', 'edit_staff', 'delete_staff',
    'add_service', 'edit_service', 'delete_service',
    'add_expense', 'delete_expense',
    'add_inventory', 'adjust_inventory',
    'update_staff_commission', 'mark_attendance',
    'export_report_csv', 'create_staff_account',
    'reports', 'export_report_csv', 'expenses', 'delete_expense',
    'suppliers', 'add_supplier', 'edit_supplier', 'purchases', 'add_purchase', 'loyalty'
}

@app.before_request
def ensure_database():
    if os.environ.get('SALON_PRO_AUTO_CREATE_DB', '1') != '1':
        return None
    try:
        if not inspect(db.engine).has_table('user'):
            init_db()
    except Exception as exc:
        app.logger.exception('Database bootstrap failed: %s', exc)
        raise

@app.before_request
def csrf_guard():
    if request.method in {'POST','PUT','PATCH','DELETE'}:
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
    if 'user_id' in session and 'role' not in session:
        user = current_user()
        if user:
            session['role'] = user.role or 'staff'
    if request.endpoint in ADMIN_ONLY_ENDPOINTS and 'user_id' in session and session.get('role') != 'admin':
        flash('Admin access is required for this action.', 'danger')
        return redirect(url_for('dashboard'))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
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
    return response

@app.route('/health')
def health():
    return jsonify(status='ok')

@app.route('/')
@login_required
def dashboard():
    today = date.today()
    start = today - timedelta(days=30)
    end = today
    appointments = Appointment.query.filter(Appointment.appointment_date.between(start, end)).all()
    revenue = db.session.query(func.coalesce(func.sum(Invoice.total), 0)).filter(Invoice.created_at >= datetime.combine(start, datetime.min.time())).scalar() or 0
    return render_template('dashboard.html', appointments=appointments, revenue=revenue, today=today)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        # In production the Render-managed admin password is the authoritative
        # credential. If it changed after the database user was first created,
        # synchronize the stored hash on a successful environment-password
        # match. This avoids an otherwise permanent lockout after a password
        # rotation without exposing the password in logs or source code.
        if user and user.role == 'admin':
            configured_password = os.environ.get('SALON_PRO_ADMIN_PASSWORD', '')
            if configured_password and secrets.compare_digest(password or '', configured_password):
                if not check_password_hash(user.password_hash, configured_password):
                    user.password_hash = generate_password_hash(configured_password)
                    db.session.commit()
                session.clear()
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = user.role or 'staff'
                flash('Welcome back!', 'success')
                return redirect(url_for('dashboard'))

        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role or 'staff'
            flash('Welcome back!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')
