# Salon Pro – Salon Management System

A complete, ready-to-use **Salon / Beauty Parlour Management Software** built with Python Flask.

## Features

- **Dashboard** – Today's appointments, monthly revenue, customer/staff/service counts
- **Customer Management** – Add, edit, search, delete customers
- **Appointment Booking** – Schedule appointments with customer, staff & service
- **Status Tracking** – Mark appointments as Completed / Cancelled / No-Show
- **Services Catalog** – Manage services with price, duration & category
- **Staff Management** – Add staff with specialties
- **Billing & Invoices** – Auto-generate invoices on completion + record payments (Cash/Card/UPI)
- **Secure Login** – Simple authentication

## Tech Stack

- Python 3 + Flask
- SQLAlchemy + SQLite
- Bootstrap 5 + Bootstrap Icons
- Jinja2 templates

## Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/gopiminhas854-coder/salon-pro.git
cd salon-pro
```

### 2. Create virtual environment (recommended)
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the application
```bash
python app.py
```

### 5. Open in browser
```
http://127.0.0.1:5000
```

## Default Login

| Username | Password  |
|----------|-----------|
| admin    | admin123  |

> Change the password after first login in production.

## Sample Data

On first run the system automatically creates:
- Admin user
- 7 sample services (Haircut, Coloring, Facial, Manicure, etc.)
- 4 sample staff members

## Project Structure

```
salon-pro/
├── app.py                 # Main application + models + routes
├── requirements.txt
├── README.md
├── static/
│   └── css/style.css
└── templates/
    ├── base.html
    ├── login.html
    ├── dashboard.html
    ├── customers.html
    ├── customer_form.html
    ├── services.html
    ├── service_form.html
    ├── staff.html
    ├── staff_form.html
    ├── appointments.html
    ├── appointment_form.html
    ├── invoices.html
    └── invoice_detail.html
```

## How to Use

1. **Login** with admin / admin123
2. **Add Customers** from the Customers menu
3. **Book Appointments** – select customer, service, staff, date & time
4. On the day of appointment, mark it as **Completed**
5. An **Invoice** is automatically created → go to Invoices and mark as Paid
6. View revenue on the Dashboard

## Customization

- Change tax rate in `app.py` (currently 5%)
- Add more service categories
- Change SECRET_KEY and default admin password for production
- Switch to PostgreSQL/MySQL by changing the database URI

## License

MIT – Free to use and modify for your salon business.

---

Made with ❤️ for salon owners
