from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import os
from sqlalchemy import func

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SALON_PRO_SECRET_KEY', 'change-this-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///salon.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==================== MODELS ====================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='admin')  # admin / staff

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

class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    description = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Float, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    invoice = db.relationship('Invoice', backref=db.backref('items', lazy=True, cascade='all, delete-orphan'))

# ==================== AUTH ====================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Welcome back!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

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
                tax=round(service.price * 0.05, 2),  # 5% tax
                total=round(service.price * 1.05, 2),
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
    return render_template('invoice_detail.html', invoice=invoice)

@app.route('/invoices/pay/<int:id>', methods=['POST'])
@login_required
def mark_paid(id):
    invoice = Invoice.query.get_or_404(id)
    invoice.payment_status = 'Paid'
    invoice.payment_method = request.form.get('payment_method', 'Cash')
    db.session.commit()
    flash('Payment recorded successfully!', 'success')
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
    db.session.commit()
    flash(f'{item.name} stock updated to {item.stock_qty:g}.', 'success')
    return redirect(url_for('inventory'))

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
    invoice.tax = round(max(invoice.amount - invoice.discount, 0) * 0.05, 2)
    invoice.total = round(max(invoice.amount - invoice.discount, 0) + invoice.tax, 2)
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
    db.session.delete(item)
    db.session.flush()
    subtotal = sum(i.total for i in invoice.items)
    invoice.amount = round(subtotal, 2)
    invoice.tax = round(max(invoice.amount - invoice.discount, 0) * 0.05, 2)
    invoice.total = round(max(invoice.amount - invoice.discount, 0) + invoice.tax, 2)
    db.session.commit()
    flash('Invoice item removed.', 'info')
    return redirect(url_for('view_invoice', id=id))

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
