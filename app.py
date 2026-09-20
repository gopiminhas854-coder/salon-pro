from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import os
from sqlalchemy import func

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SALON_PRO_SECRET_KEY', 'change-this-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///salon.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

db = SQLAlchemy(app)

# ==================== MODELS ====================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='admin')  # admin / staff

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
    category = db.Column(db.String(50))  # Hair, Skin, Nails, etc.
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
    status = db.Column(db.String(20), default='Scheduled')  # Scheduled, Completed, Cancelled, No-Show
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
    payment_status = db.Column(db.String(20), default='Pending')  # Pending, Paid
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

class SalonSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    salon_name = db.Column(db.String(120), default='Salon Pro')
    phone = db.Column(db.String(30))
    address = db.Column(db.Text)
    tax_rate = db.Column(db.Float, default=5)
    loyalty_rate = db.Column(db.Float, default=1)
    reminder_days = db.Column(db.Integer, default=1)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    return round(sum(p.amount for p in invoice.payments), 2)

def invoice_balance(invoice):
    return round(max(invoice.total - invoice_paid_amount(invoice), 0), 2)

@app.context_processor
def template_helpers():
    return {'invoice_paid_amount': invoice_paid_amount, 'invoice_balance': invoice_balance}


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
    'reminders'
}

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

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'Salon Pro'}), 200

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role or 'staff'
            flash('Welcome back!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

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
    points = max(0, int(round(max(invoice.total, 0) * rate)))
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

# ==================== CALENDAR / BOOKING ====================

@app.route('/calendar')
@login_required
def calendar_view():
    selected_text = request.args.get('date', date.today().isoformat())
    try:
        selected = datetime.strptime(selected_text, '%Y-%m-%d').date()
    except ValueError:
        selected = date.today()
        selected_text = selected.isoformat()
    week_start = selected - timedelta(days=selected.weekday())
    days = [week_start + timedelta(days=i) for i in range(7)]
    appointments_by_day = {
        d: Appointment.query.filter_by(appointment_date=d).order_by(Appointment.appointment_time).all()
        for d in days
    }
    return render_template('calendar.html', selected=selected, selected_text=selected_text,
                           week_start=week_start, days=days, appointments_by_day=appointments_by_day,
                           previous_week=(selected - timedelta(days=7)).isoformat(),
                           next_week=(selected + timedelta(days=7)).isoformat(), today_iso=date.today().isoformat())

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
            Staff.query.filter_by(id=staff_id, is_active=True).first_or_404()
            start = datetime.combine(appointment_date, datetime.strptime(appointment_time, '%H:%M').time())
            end = start + timedelta(minutes=service.duration_minutes or 30)
            conflicts = Appointment.query.filter_by(
                staff_id=staff_id, appointment_date=appointment_date, status='Scheduled'
            ).all()
            if any(
                start < datetime.combine(appointment_date, datetime.strptime(a.appointment_time, '%H:%M').time())
                + timedelta(minutes=a.service.duration_minutes or 30)
                and datetime.combine(appointment_date, datetime.strptime(a.appointment_time, '%H:%M').time()) < end
                for a in conflicts
            ):
                flash('That time is already booked. Please choose another time.', 'danger')
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

@app.route('/backup/download')
@admin_required
def download_backup():
    db_path = os.path.join(app.instance_path, 'salon.db')
    if not os.path.exists(db_path):
        db_path = os.path.abspath('salon.db')
    if not os.path.exists(db_path):
        flash('Database file was not found.', 'danger')
        return redirect(url_for('dashboard'))
    return send_file(db_path, as_attachment=True, download_name=f"salon-pro-backup-{date.today().isoformat()}.db")

# ==================== DASHBOARD ====================

@app.route('/')
@login_required
def dashboard():
    today = date.today()
    today_appointments = Appointment.query.filter_by(appointment_date=today).order_by(Appointment.appointment_time).all()
    
    total_customers = Customer.query.count()
    total_staff = Staff.query.filter_by(is_active=True).count()
    total_services = Service.query.filter_by(is_active=True).count()
    
    # Revenue this month
    first_day = today.replace(day=1)
    paid_invoices = Invoice.query.filter(
        Invoice.payment_status == 'Paid',
        Invoice.created_at >= first_day
    ).all()
    monthly_revenue = sum(inv.total for inv in paid_invoices)
    monthly_expenses = sum(e.amount for e in Expense.query.filter(Expense.expense_date >= first_day, Expense.expense_date <= today).all())
    monthly_profit = monthly_revenue - monthly_expenses
    
    # Upcoming appointments (next 7 days)
    next_week = today + timedelta(days=7)
    upcoming = Appointment.query.filter(
        Appointment.appointment_date > today,
        Appointment.appointment_date <= next_week,
        Appointment.status == 'Scheduled'
    ).order_by(Appointment.appointment_date, Appointment.appointment_time).limit(5).all()
    
    pending_invoices = Invoice.query.filter_by(payment_status='Pending').count()
    today_revenue = sum(i.total for i in Invoice.query.filter(Invoice.payment_status == 'Paid', func.date(Invoice.created_at) == today).all())
    completed_today = Appointment.query.filter_by(appointment_date=today, status='Completed').count()
    low_stock_count = InventoryItem.query.filter(InventoryItem.is_active == True,
                                                 InventoryItem.stock_qty <= InventoryItem.reorder_level).count()
    return render_template('dashboard.html',
                           today_appointments=today_appointments,
                           total_customers=total_customers,
                           total_staff=total_staff,
                           total_services=total_services,
                           monthly_revenue=monthly_revenue,
                           monthly_expenses=monthly_expenses,
                           monthly_profit=monthly_profit,
                           pending_invoices=pending_invoices,
                           today_revenue=today_revenue,
                           completed_today=completed_today,
                           low_stock_count=low_stock_count,
                           upcoming=upcoming,
                           today=today)

# ==================== CUSTOMERS ====================

@app.route('/customers')
@login_required
def customers():
    search = request.args.get('search', '')
    if search:
        customers_list = Customer.query.filter(
            db.or_(Customer.name.ilike(f'%{search}%'), Customer.phone.ilike(f'%{search}%'))
        ).order_by(Customer.name).all()
    else:
        customers_list = Customer.query.order_by(Customer.created_at.desc()).all()
    return render_template('customers.html', customers=customers_list, search=search)

@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        customer = Customer(
            name=request.form['name'],
            phone=request.form['phone'],
            email=request.form.get('email'),
            gender=request.form.get('gender'),
            address=request.form.get('address'),
            notes=request.form.get('notes')
        )
        db.session.add(customer)
        db.session.commit()
        flash('Customer added successfully!', 'success')
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=None)

@app.route('/customers/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_customer(id):
    customer = Customer.query.get_or_404(id)
    if request.method == 'POST':
        customer.name = request.form['name']
        customer.phone = request.form['phone']
        customer.email = request.form.get('email')
        customer.gender = request.form.get('gender')
        customer.address = request.form.get('address')
        customer.notes = request.form.get('notes')
        db.session.commit()
        flash('Customer updated successfully!', 'success')
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=customer)

@app.route('/customers/delete/<int:id>', methods=['POST'])
@login_required
def delete_customer(id):
    customer = Customer.query.get_or_404(id)
    db.session.delete(customer)
    db.session.commit()
    flash('Customer deleted.', 'info')
    return redirect(url_for('customers'))

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
    total_spend = sum(i.total for i in customer_invoices if i.payment_status == 'Paid')
    pending_amount = sum(i.total for i in customer_invoices if i.payment_status == 'Pending')
    last_visit = Appointment.query.filter_by(customer_id=id, status='Completed').order_by(
        Appointment.appointment_date.desc()
    ).first()
    return render_template('customer_detail.html', customer=customer,
                           appointments=customer_appointments, invoices=customer_invoices,
                           completed_visits=completed_visits, total_spend=total_spend,
                           pending_amount=pending_amount, last_visit=last_visit)


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
        service = Service(
            name=request.form['name'],
            description=request.form.get('description'),
            duration_minutes=int(request.form.get('duration_minutes', 30)),
            price=float(request.form['price']),
            category=request.form.get('category'),
            is_active=True
        )
        db.session.add(service)
        db.session.commit()
        flash('Service added successfully!', 'success')
        return redirect(url_for('services'))
    return render_template('service_form.html', service=None)

@app.route('/services/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_service(id):
    service = Service.query.get_or_404(id)
    if request.method == 'POST':
        service.name = request.form['name']
        service.description = request.form.get('description')
        service.duration_minutes = int(request.form.get('duration_minutes', 30))
        service.price = float(request.form['price'])
        service.category = request.form.get('category')
        service.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Service updated!', 'success')
        return redirect(url_for('services'))
    return render_template('service_form.html', service=service)

@app.route('/services/delete/<int:id>', methods=['POST'])
@login_required
def delete_service(id):
    service = Service.query.get_or_404(id)
    db.session.delete(service)
    db.session.commit()
    flash('Service deleted.', 'info')
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
    db.session.delete(member)
    db.session.commit()
    flash('Staff member deleted.', 'info')
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
        user = User(username=username, password_hash=generate_password_hash(password), role='staff')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserStaffLink(user_id=user.id, staff_id=member.id))
        db.session.commit()
        flash(f'Login account created for {member.name}.', 'success')
        return redirect(url_for('staff'))
    return render_template('staff_account.html', member=member)

# ==================== APPOINTMENTS ====================

@app.route('/appointments')
@login_required
def appointments():
    status_filter = request.args.get('status', '')
    date_filter = request.args.get('date', '')
    
    query = Appointment.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    if date_filter:
        query = query.filter_by(appointment_date=datetime.strptime(date_filter, '%Y-%m-%d').date())
    
    appointments_list = query.order_by(Appointment.appointment_date.desc(), Appointment.appointment_time).all()
    return render_template('appointments.html', appointments=appointments_list,
                           status_filter=status_filter, date_filter=date_filter)

@app.route('/appointments/add', methods=['GET', 'POST'])
@login_required
def add_appointment():
    if request.method == 'POST':
        appointment_date = datetime.strptime(request.form['appointment_date'], '%Y-%m-%d').date()
        appointment_time = request.form['appointment_time']
        staff_id = int(request.form['staff_id'])
        service_id = int(request.form['service_id'])
        service = Service.query.get_or_404(service_id)
        start = datetime.combine(appointment_date, datetime.strptime(appointment_time, '%H:%M').time())
        end = start + timedelta(minutes=service.duration_minutes or 30)
        conflicts = Appointment.query.filter_by(staff_id=staff_id, appointment_date=appointment_date, status='Scheduled').all()
        for existing in conflicts:
            existing_service = existing.service
            existing_start = datetime.combine(appointment_date, datetime.strptime(existing.appointment_time, '%H:%M').time())
            existing_end = existing_start + timedelta(minutes=existing_service.duration_minutes or 30)
            if start < existing_end and existing_start < end:
                flash(f'Staff member is already booked from {existing.appointment_time}. Please choose another time.', 'danger')
                return redirect(url_for('add_appointment'))
        appt = Appointment(
            customer_id=int(request.form['customer_id']), staff_id=staff_id, service_id=service_id,
            appointment_date=appointment_date, appointment_time=appointment_time,
            notes=request.form.get('notes'), status='Scheduled')
        db.session.add(appt)
        db.session.commit()
        flash('Appointment booked successfully!', 'success')
        return redirect(url_for('appointments'))
    
    customers = Customer.query.order_by(Customer.name).all()
    staff_list = Staff.query.filter_by(is_active=True).order_by(Staff.name).all()
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    return render_template('appointment_form.html', appointment=None,
                           customers=customers, staff_list=staff_list, services=services)

@app.route('/appointments/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_appointment(id):
    appt = Appointment.query.get_or_404(id)
    if request.method == 'POST':
        appointment_date = datetime.strptime(request.form['appointment_date'], '%Y-%m-%d').date()
        appointment_time = request.form['appointment_time']
        staff_id = int(request.form['staff_id'])
        service_id = int(request.form['service_id'])
        service = Service.query.get_or_404(service_id)
        start = datetime.combine(appointment_date, datetime.strptime(appointment_time, '%H:%M').time())
        end = start + timedelta(minutes=service.duration_minutes or 30)
        conflicts = Appointment.query.filter(Appointment.id != appt.id, Appointment.staff_id == staff_id, Appointment.appointment_date == appointment_date, Appointment.status == 'Scheduled').all()
        for existing in conflicts:
            existing_start = datetime.combine(appointment_date, datetime.strptime(existing.appointment_time, '%H:%M').time())
            existing_end = existing_start + timedelta(minutes=existing.service.duration_minutes or 30)
            if start < existing_end and existing_start < end:
                flash(f'Staff member is already booked from {existing.appointment_time}. Please choose another time.', 'danger')
                return redirect(url_for('edit_appointment', id=id))
        appt.customer_id = int(request.form['customer_id'])
        appt.staff_id = int(request.form['staff_id'])
        appt.service_id = int(request.form['service_id'])
        appt.appointment_date = appointment_date
        appt.appointment_time = appointment_time
        appt.status = request.form['status']
        appt.notes = request.form.get('notes')
        db.session.commit()
        flash('Appointment updated!', 'success')
        return redirect(url_for('appointments'))
    
    customers = Customer.query.order_by(Customer.name).all()
    staff_list = Staff.query.filter_by(is_active=True).order_by(Staff.name).all()
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    return render_template('appointment_form.html', appointment=appt,
                           customers=customers, staff_list=staff_list, services=services)

@app.route('/appointments/status/<int:id>/<status>', methods=['POST'])
@login_required
def update_appointment_status(id, status):
    appt = Appointment.query.get_or_404(id)
    appt.status = status
    db.session.commit()
    
    # Auto-create invoice when completed
    if status == 'Completed':
        existing = Invoice.query.filter_by(appointment_id=appt.id).first()
        if not existing:
            service = Service.query.get(appt.service_id)
            inv = Invoice(
                appointment_id=appt.id,
                customer_id=appt.customer_id,
                amount=service.price,
                discount=0,
                tax=round(service.price * get_tax_rate() / 100, 2),
                total=round(service.price * (1 + get_tax_rate() / 100), 2),
                payment_status='Pending'
            )
            db.session.add(inv)
            db.session.flush()
            db.session.add(InvoiceItem(invoice_id=inv.id, description=service.name,
                                       quantity=1, unit_price=service.price,
                                       total=service.price))
            db.session.commit()
            flash(f'Appointment marked as Completed. Invoice created (₹{inv.total}).', 'success')
        else:
            flash('Status updated.', 'success')
    else:
        flash('Status updated.', 'success')
    return redirect(url_for('appointments'))

# ==================== INVOICES / BILLING ====================

@app.route('/invoices')
@login_required
def invoices():
    invoices_list = Invoice.query.order_by(Invoice.created_at.desc()).all()
    return render_template('invoices.html', invoices=invoices_list)

@app.route('/invoices/<int:id>')
@login_required
def view_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    inventory_products = InventoryItem.query.filter_by(is_active=True).order_by(InventoryItem.name).all()
    return render_template('invoice_detail.html', invoice=invoice, inventory_products=inventory_products)

@app.route('/invoices/pay/<int:id>', methods=['POST'])
@login_required
def mark_paid(id):
    invoice = Invoice.query.get_or_404(id)
    balance = invoice_balance(invoice)
    if balance <= 0:
        invoice.payment_status = 'Paid'
        award_loyalty_for_invoice(invoice)
        db.session.commit()
        return redirect(url_for('view_invoice', id=id))
    method = request.form.get('payment_method', 'Cash')
    try:
        amount = float(request.form.get('amount', balance))
        if amount <= 0 or amount > balance + 0.01:
            raise ValueError
    except (ValueError, TypeError):
        flash(f'Payment must be between ₹0.01 and ₹{balance:.2f}.', 'danger')
        return redirect(url_for('view_invoice', id=id))
    amount = round(min(amount, balance), 2)
    db.session.add(InvoicePayment(invoice_id=invoice.id, amount=amount,
                                  payment_method=method, notes=request.form.get('notes')))
    invoice.payment_method = method
    db.session.flush()
    paid = invoice_paid_amount(invoice)
    invoice.payment_status = 'Paid' if paid >= invoice.total - 0.01 else 'Partial'
    if invoice.payment_status == 'Paid':
        award_loyalty_for_invoice(invoice)
    db.session.commit()
    flash(f'Payment of ₹{amount:.2f} recorded. Balance: ₹{invoice_balance(invoice):.2f}.', 'success')
    return redirect(url_for('view_invoice', id=id))

# ==================== INVENTORY ====================

@app.route('/inventory')
@login_required
def inventory():
    items = InventoryItem.query.order_by(InventoryItem.name).all()
    low_stock = [i for i in items if i.is_active and i.stock_qty <= i.reorder_level]
    return render_template('inventory.html', items=items, low_stock=low_stock)

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
    item = InventoryItem.query.get_or_404(id)
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
            item = InventoryItem.query.get_or_404(int(request.form['inventory_item_id']))
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
    paid_revenue = sum(
        inv.total for inv in Invoice.query.join(Appointment, Invoice.appointment_id == Appointment.id)
        .filter(Appointment.staff_id == id, Invoice.payment_status == 'Paid',
                func.date(Invoice.created_at) >= start, func.date(Invoice.created_at) <= end).all()
    )
    settings = StaffCommission.query.filter_by(staff_id=id).first()
    rate = settings.commission_rate if settings else 0
    commission = round(paid_revenue * rate / 100, 2)
    return render_template('staff_performance.html', member=member, appointments=appointments,
                           completed_count=len(completed), paid_revenue=paid_revenue,
                           rate=rate, commission=commission, start=start_text, end=end_text)

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

    paid = Invoice.query.filter(
        Invoice.payment_status == 'Paid',
        func.date(Invoice.created_at) >= start,
        func.date(Invoice.created_at) <= end
    ).all()
    pending = Invoice.query.filter(
        Invoice.payment_status == 'Pending',
        func.date(Invoice.created_at) >= start,
        func.date(Invoice.created_at) <= end
    ).all()
    expenses_list = Expense.query.filter(Expense.expense_date >= start, Expense.expense_date <= end).all()
    appts = Appointment.query.filter(Appointment.appointment_date >= start, Appointment.appointment_date <= end).all()

    revenue = round(sum(i.total for i in paid), 2)
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

    staff_rows = []
    for member in Staff.query.order_by(Staff.name).all():
        member_appts = [a for a in appts if a.staff_id == member.id]
        member_paid = sum(
            inv.total for inv in paid
            if inv.appointment and inv.appointment.staff_id == member.id
        )
        settings = StaffCommission.query.filter_by(staff_id=member.id).first()
        rate = settings.commission_rate if settings else 0
        commission = round(member_paid * rate / 100, 2)
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
            daily[day_key] += inv.total
    daily_rows = [{'date': k, 'revenue': round(v, 2)} for k, v in daily.items()]

    return render_template('reports.html', start=start_text, end=end_text, revenue=revenue,
                           expenses_total=expenses_total, profit=profit, paid_count=len(paid),
                           pending_count=len(pending), completed=completed, no_show=no_show,
                           cancelled=cancelled, top_services=top_services,
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

    paid = Invoice.query.filter(Invoice.payment_status == 'Paid',
                                 func.date(Invoice.created_at) >= start,
                                 func.date(Invoice.created_at) <= end).all()
    expenses_list = Expense.query.filter(Expense.expense_date >= start, Expense.expense_date <= end).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Salon Pro Report', start.isoformat(), end.isoformat()])
    writer.writerow([])
    writer.writerow(['Paid Invoice ID', 'Date', 'Customer', 'Total', 'Payment Method'])
    for inv in paid:
        writer.writerow([inv.id, inv.created_at.strftime('%Y-%m-%d'), inv.customer.name if inv.customer else '',
                         f'{inv.total:.2f}', inv.payment_method or ''])
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
        paid = sum(i.total for i in Invoice.query.filter_by(customer_id=customer.id, payment_status='Paid').all())
        points = loyalty.points if loyalty else int(paid * (SalonSetting.query.first().loyalty_rate if SalonSetting.query.first() else 1) / 100)
        rows.append({'customer': customer, 'points': points, 'spend': round(paid,2)})
    rows.sort(key=lambda x: (-x['points'], x['customer'].name.lower()))
    return render_template('loyalty.html', rows=rows)

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
        Appointment.status == 'Scheduled'
    ).order_by(Appointment.appointment_date, Appointment.appointment_time).all()
    return render_template('reminders.html', upcoming=upcoming, days=days)

# ==================== INVENTORY SALES ====================

@app.route('/invoices/<int:id>/inventory-sale', methods=['POST'])
@login_required
def add_inventory_sale(id):
    invoice = Invoice.query.get_or_404(id)
    try:
        item_id = int(request.form['inventory_item_id'])
        quantity = float(request.form['quantity'])
        if quantity <= 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        flash('Enter a valid product and quantity.', 'danger')
        return redirect(url_for('view_invoice', id=id))
    item = InventoryItem.query.get_or_404(item_id)
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
        setting.salon_name = request.form.get('salon_name','Salon Pro').strip() or 'Salon Pro'
        setting.phone = request.form.get('phone','').strip()
        setting.address = request.form.get('address','').strip()
        try:
            setting.tax_rate = max(0, min(100, float(request.form.get('tax_rate', 5))))
            setting.loyalty_rate = max(0, min(100, float(request.form.get('loyalty_rate', 1))))
            setting.reminder_days = max(1, min(30, int(request.form.get('reminder_days', 1))))
        except (ValueError, TypeError):
            flash('Enter valid numeric settings.', 'danger')
            return render_template('settings.html', setting=setting)
        db.session.commit()
        flash('Salon settings saved.', 'success')
        return redirect(url_for('settings'))
    return render_template('settings.html', setting=setting)

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
        db.session.commit()
        # Create default admin if not exists
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password_hash=generate_password_hash('admin123'),
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
