import os
import sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Keep the CI database outside the checked-out repository. Flask-SQLAlchemy
# resolves relative SQLite paths under the instance directory, which can
# produce a readonly database when fixtures repeatedly reset the file.
os.environ["DATABASE_URL"] = "sqlite:////tmp/salon_ci.db"
os.environ["SALON_PRO_SECRET_KEY"] = "test-secret"

import app as salon

@pytest.fixture()
def client():
    salon.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=os.environ["DATABASE_URL"])
    with salon.app.app_context():
        salon.db.session.remove()
        salon.db.drop_all()
        salon.db.create_all()
        user = salon.User(username="admin", password_hash=salon.generate_password_hash("admin123"), role="admin")
        customer = salon.Customer(name="Test Customer", phone="9999999999")
        service = salon.Service(name="Test Haircut", duration_minutes=30, price=100, category="Hair", is_active=True)
        staff = salon.Staff(name="Test Stylist", is_active=True)
        item = salon.InventoryItem(name="Test Shampoo", sku="TEST-1", stock_qty=10, reorder_level=2, cost_price=20, sale_price=50, is_active=True)
        salon.db.session.add_all([user, customer, service, staff, item])
        salon.db.session.commit()
    with salon.app.test_client() as c:
        yield c, salon
    with salon.app.app_context():
        salon.db.session.remove()

def login(c):
    return c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)

def test_health_and_login(client):
    c, salon = client
    assert c.get("/health").status_code == 200
    assert b'"status":"ok"' in c.get("/health").data
    response = login(c)
    assert response.status_code == 200
    assert b"Overview" in response.data

def test_core_pages_load(client):
    c, _ = client
    login(c)
    for path in ["/", "/customers", "/appointments", "/calendar", "/services", "/staff",
                 "/attendance", "/reports", "/invoices", "/expenses", "/inventory",
                 "/inventory/transactions", "/suppliers", "/purchases", "/loyalty",
                 "/reminders", "/settings"]:
        assert c.get(path).status_code == 200, path

def test_public_booking_and_conflict_detection(client):
    c, salon = client
    with salon.app.app_context():
        service = salon.Service.query.first()
        staff = salon.Staff.query.first()
    first = c.post("/book", data={
        "name": "Online Customer", "phone": "8888888888",
        "service_id": service.id, "staff_id": staff.id,
        "appointment_date": "2030-01-15", "appointment_time": "10:00"
    }, follow_redirects=True)
    assert first.status_code == 200
    second = c.post("/book", data={
        "name": "Second Customer", "phone": "7777777777",
        "service_id": service.id, "staff_id": staff.id,
        "appointment_date": "2030-01-15", "appointment_time": "10:15"
    }, follow_redirects=True)
    assert second.status_code == 200
    assert b"already booked" in second.data

def test_invoice_payment_and_duplicate_loyalty_protection(client):
    c, salon = client
    login(c)
    with salon.app.app_context():
        customer = salon.Customer.query.first()
        service = salon.Service.query.first()
        staff = salon.Staff.query.first()
        appt = salon.Appointment(customer_id=customer.id, staff_id=staff.id, service_id=service.id,
                                 appointment_date=salon.date.today(), appointment_time="11:00", status="Completed")
        salon.db.session.add(appt)
        salon.db.session.flush()
        inv = salon.Invoice(appointment_id=appt.id, customer_id=customer.id, amount=100,
                            discount=0, tax=5, total=105, payment_status="Pending")
        salon.db.session.add(inv)
        salon.db.session.flush()
        salon.db.session.add(salon.InvoiceItem(invoice_id=inv.id, description=service.name, quantity=1,
                                               unit_price=100, total=100))
        salon.db.session.commit()
        inv_id = inv.id
    response = c.post(f"/invoices/pay/{inv_id}", data={"amount": "50", "payment_method": "Cash"}, follow_redirects=True)
    assert response.status_code == 200
    with salon.app.app_context():
        inv = salon.Invoice.query.get(inv_id)
        assert inv.payment_status == "Partial"
        assert round(salon.invoice_balance(inv), 2) == 55
    c.post(f"/invoices/pay/{inv_id}", data={"amount": "55", "payment_method": "UPI"}, follow_redirects=True)
    with salon.app.app_context():
        inv = salon.Invoice.query.get(inv_id)
        assert inv.payment_status == "Paid"
        assert salon.InvoicePayment.query.filter_by(invoice_id=inv_id).count() == 2
        assert salon.LoyaltyTransaction.query.filter_by(reference=f"invoice:{inv_id}").count() == 1

def test_inventory_sale_and_item_removal_restore_stock(client):
    c, salon = client
    login(c)
    with salon.app.app_context():
        customer = salon.Customer.query.first()
        service = salon.Service.query.first()
        staff = salon.Staff.query.first()
        item = salon.InventoryItem.query.first()
        appt = salon.Appointment(customer_id=customer.id, staff_id=staff.id, service_id=service.id,
                                 appointment_date=salon.date.today(), appointment_time="12:00", status="Completed")
        salon.db.session.add(appt)
        salon.db.session.flush()
        inv = salon.Invoice(appointment_id=appt.id, customer_id=customer.id, amount=100,
                            discount=0, tax=5, total=105, payment_status="Pending")
        salon.db.session.add(inv)
        salon.db.session.flush()
        salon.db.session.add(salon.InvoiceItem(invoice_id=inv.id, description=service.name, quantity=1,
                                               unit_price=100, total=100))
        salon.db.session.commit()
        inv_id, item_id = inv.id, item.id
    response = c.post(f"/invoices/{inv_id}/inventory-sale",
                      data={"inventory_item_id": item_id, "quantity": "2"}, follow_redirects=True)
    assert response.status_code == 200
    with salon.app.app_context():
        item = salon.InventoryItem.query.get(item_id)
        inv = salon.Invoice.query.get(inv_id)
        assert item.stock_qty == 8
        assert salon.InventorySale.query.filter_by(invoice_id=inv_id).count() == 1
        sale = salon.InventorySale.query.filter_by(invoice_id=inv_id).first()
        line = salon.InventorySaleLine.query.filter_by(inventory_sale_id=sale.id).first()
        assert line is not None
        product_item = salon.InvoiceItem.query.filter_by(invoice_id=inv_id, description=item.name).first()
        product_item_id = product_item.id
    response = c.post(f"/invoices/{inv_id}/items/{product_item_id}/delete", follow_redirects=True)
    assert response.status_code == 200
    with salon.app.app_context():
        assert salon.InventoryItem.query.get(item_id).stock_qty == 10
        assert salon.InventorySaleLine.query.filter_by(invoice_item_id=product_item_id).first() is None

def test_purchase_increases_stock(client):
    c, salon = client
    login(c)
    with salon.app.app_context():
        item = salon.InventoryItem.query.first()
        item_id = item.id
    response = c.post("/purchases/add", data={
        "inventory_item_id": str(item_id), "quantity": "3", "unit_cost": "25",
        "purchase_date": "2030-01-15", "reference": "BILL-1", "notes": "test"
    }, follow_redirects=True)
    assert response.status_code == 200
    with salon.app.app_context():
        assert salon.InventoryItem.query.get(item_id).stock_qty == 13
        assert salon.InventoryPurchase.query.count() == 1
        assert salon.InventoryTransaction.query.filter_by(transaction_type="Purchase").count() >= 1

def test_business_hours_block_booking(client):
    c, salon = client
    with salon.app.app_context():
        h = salon.SalonHours(day_of_week=1, open_time='10:00', close_time='18:00', is_closed=False)
        salon.db.session.add(h)
        salon.db.session.commit()
        service = salon.Service.query.first()
        staff = salon.Staff.query.first()
    response = c.post('/book', data={'name':'Closed Hours','phone':'6666666666','service_id':service.id,'staff_id':staff.id,'appointment_date':'2030-01-15','appointment_time':'09:00'}, follow_redirects=True)
    assert b'Bookings are available' in response.data

def test_staff_cannot_access_admin_endpoints(client):
    c, salon = client
    with salon.app.app_context():
        staff_user = salon.User(username="staff", password_hash=salon.generate_password_hash("staff12345"), role="staff")
        salon.db.session.add(staff_user)
        salon.db.session.commit()
    response = c.post("/login", data={"username": "staff", "password": "staff12345"}, follow_redirects=True)
    assert response.status_code == 200
    assert c.get("/settings").status_code == 302
    assert c.post("/inventory/adjust/1", data={"change": "1"}).status_code == 302

def test_refund_reverses_loyalty_and_inventory(client):
    c, salon = client
    login(c)
    with salon.app.app_context():
        customer = salon.Customer.query.first()
        service = salon.Service.query.first()
        item = salon.InventoryItem.query.first()
        appt = salon.Appointment(customer_id=customer.id, staff_id=salon.Staff.query.first().id, service_id=service.id,
                                 appointment_date=salon.date.today(), appointment_time='13:00', status='Completed')
        salon.db.session.add(appt); salon.db.session.flush()
        inv = salon.Invoice(appointment_id=appt.id, customer_id=customer.id, amount=100, discount=0, tax=5, total=105, payment_status='Pending')
        salon.db.session.add(inv); salon.db.session.flush()
        salon.db.session.add(salon.InvoiceItem(invoice_id=inv.id, description=service.name, quantity=1, unit_price=100, total=100))
        salon.db.session.commit()
        inv_id, item_id = inv.id, item.id
    c.post(f'/invoices/{inv_id}/inventory-sale', data={'inventory_item_id':item_id,'quantity':'1'})
    c.post(f'/invoices/pay/{inv_id}', data={'amount':'157.5','payment_method':'Cash'})
    with salon.app.app_context():
        assert salon.Invoice.query.get(inv_id).payment_status == 'Paid'
        before = salon.InventoryItem.query.get(item_id).stock_qty
    c.post(f'/invoices/refund/{inv_id}', data={'amount':'157.5','refund_method':'Cash','reason':'Test refund'}, follow_redirects=True)
    with salon.app.app_context():
        assert salon.Invoice.query.get(inv_id).payment_status == 'Refunded'
        assert salon.InventoryItem.query.get(item_id).stock_qty == before + 1
        assert salon.LoyaltyTransaction.query.filter_by(transaction_type='Refund').count() == 1

def test_completed_appointment_invoice_is_created_atomically():
    with salon.app.test_client() as client:
        login(client)
        with salon.app.app_context():
            customer = salon.Customer.query.first()
            service = salon.Service.query.first()
            staff = salon.Staff.query.first()
            appt = salon.Appointment(
                customer_id=customer.id,
                staff_id=staff.id,
                service_id=service.id,
                appointment_date=salon.date.today(),
                appointment_time="14:00",
                status="Scheduled",
            )
            salon.db.session.add(appt)
            salon.db.session.commit()
            appointment_id = appt.id
            service_price = service.price

        response = client.post(f'/appointments/status/{appointment_id}/Completed')
        assert response.status_code == 302

        with salon.app.app_context():
            invoice = salon.Invoice.query.filter_by(appointment_id=appointment_id).first()
            assert invoice is not None
            assert invoice.payment_status == 'Pending'
            assert invoice.amount == service_price
            assert invoice.total > invoice.amount


def test_migration_extension_is_configured():
    assert salon.migrate is not None
    assert salon.app.extensions.get('migrate') is not None


def test_advanced_crm_and_bi_apis(client):
    c, salon = client
    login(c)
    with salon.app.app_context():
        customer = salon.Customer.query.first()
        service = salon.Service.query.first()
        staff = salon.Staff.query.first()
        appt1 = salon.Appointment(customer_id=customer.id, staff_id=staff.id, service_id=service.id,
                                   appointment_date=salon.date.today() - salon.timedelta(days=30),
                                   appointment_time="10:00", status="Completed")
        appt2 = salon.Appointment(customer_id=customer.id, staff_id=staff.id, service_id=service.id,
                                   appointment_date=salon.date.today() - salon.timedelta(days=5),
                                   appointment_time="11:00", status="Completed")
        salon.db.session.add_all([appt1, appt2])
        salon.db.session.flush()
        for appt in (appt1, appt2):
            inv = salon.Invoice(appointment_id=appt.id, customer_id=customer.id, amount=100,
                                discount=0, tax=5, total=105, payment_status="Paid",
                                created_at=salon.datetime.combine(appt.appointment_date, salon.datetime.min.time()))
            salon.db.session.add(inv)
            salon.db.session.flush()
            salon.db.session.add(salon.InvoiceItem(invoice_id=inv.id, description=service.name,
                                                   quantity=1, unit_price=100, total=100))
            salon.db.session.add(salon.InvoicePayment(invoice_id=inv.id, amount=105,
                                                      payment_method="Cash"))
        salon.db.session.commit()

    response = c.get("/api/crm/summary")
    assert response.status_code == 200
    data = response.get_json()
    assert data["repeat_customers"] == 1
    row = next(x for x in data["customers"] if x["name"] == "Test Customer")
    assert row["visits"] == 2
    assert row["paid_revenue"] == 210
    assert row["favorite_service"] == "Test Haircut"
    assert row["avg_visit_interval_days"] == 25

    response = c.get("/api/business-intelligence")
    assert response.status_code == 200
    bi = response.get_json()
    assert bi["financial"]["net_revenue"] == 210
    assert bi["financial"]["average_paid_invoice"] == 105
    assert bi["appointments"]["completion_rate"] == 100
    assert bi["customers"]["repeat_customer_rate"] == 100
    assert bi["inventory"]["stock_value_at_cost"] == 200
    assert bi["inventory"]["low_stock_items"] == 0
