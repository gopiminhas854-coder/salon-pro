from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'salon-pro-secret-key-change-in-production'
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
    
    # Upcoming appointments (next 7 days)
    next_week = today + timedelta(days=7)
    upcoming = Appointment.query.filter(
        Appointment.appointment_date > today,
        Appointment.appointment_date <= next_week,
        Appointment.status == 'Scheduled'
    ).order_by(Appointment.appointment_date, Appointment.appointment_time).limit(5).all()
    
    return render_template('dashboard.html',
                           today_appointments=today_appointments,
                           total_customers=total_customers,
                           total_staff=total_staff,
                           total_services=total_services,
                           monthly_revenue=monthly_revenue,
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
        appt = Appointment(
            customer_id=int(request.form['customer_id']),
            staff_id=int(request.form['staff_id']),
            service_id=int(request.form['service_id']),
            appointment_date=datetime.strptime(request.form['appointment_date'], '%Y-%m-%d').date(),
            appointment_time=request.form['appointment_time'],
            notes=request.form.get('notes'),
            status='Scheduled'
        )
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
        appt.customer_id = int(request.form['customer_id'])
        appt.staff_id = int(request.form['staff_id'])
        appt.service_id = int(request.form['service_id'])
        appt.appointment_date = datetime.strptime(request.form['appointment_date'], '%Y-%m-%d').date()
        appt.appointment_time = request.form['appointment_time']
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

# ==================== INIT DB ====================

def init_db():
    with app.app_context():
        db.create_all()
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
