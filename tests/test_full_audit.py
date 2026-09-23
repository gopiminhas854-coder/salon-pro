import os

os.environ["DATABASE_URL"] = "sqlite:////tmp/salon_ci_audit.db"
os.environ["SALON_PRO_SECRET_KEY"] = "test-secret"
os.environ["SALON_PRO_ADMIN_PASSWORD"] = "test-admin-password"
os.environ["SALON_PRO_AUTO_CREATE_DB"] = "1"

import app as salon


def setup_database():
    salon.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=os.environ["DATABASE_URL"])
    with salon.app.app_context():
        salon.db.session.remove()
        salon.db.drop_all()
        salon.db.create_all()
        salon.db.session.add_all([
            salon.User(username="admin", password_hash=salon.generate_password_hash("admin123"), role="admin"),
            salon.Customer(name="Audit Customer", phone="9999999999"),
            salon.Service(name="Audit Haircut", duration_minutes=30, price=100, category="Hair", is_active=True),
            salon.Staff(name="Audit Stylist", is_active=True),
            salon.InventoryItem(name="Audit Shampoo", sku="AUDIT-1", stock_qty=10, reorder_level=2, cost_price=20, sale_price=50, is_active=True),
        ])
        salon.db.session.commit()


def login(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )
    assert response.status_code == 200


def test_invalid_appointment_status_is_rejected():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        with salon.app.app_context():
            customer = salon.Customer.query.first()
            service = salon.Service.query.first()
            staff = salon.Staff.query.first()
            appt = salon.Appointment(
                customer_id=customer.id,
                service_id=service.id,
                staff_id=staff.id,
                appointment_date=salon.date.today(),
                appointment_time="10:00",
                status="Scheduled",
            )
            salon.db.session.add(appt)
            salon.db.session.commit()
            appt_id = appt.id
        response = client.post(f"/appointments/status/{appt_id}/INVALID")
        assert response.status_code == 302
        with salon.app.app_context():
            assert salon.Appointment.query.get(appt_id).status == "Scheduled"


def test_customer_service_and_staff_history_cannot_be_deleted():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        with salon.app.app_context():
            customer = salon.Customer.query.first()
            service = salon.Service.query.first()
            staff = salon.Staff.query.first()
            appt = salon.Appointment(
                customer_id=customer.id,
                service_id=service.id,
                staff_id=staff.id,
                appointment_date=salon.date.today(),
                appointment_time="11:00",
                status="Scheduled",
            )
            salon.db.session.add(appt)
            salon.db.session.flush()
            salon.db.session.add(salon.StaffAttendance(staff_id=staff.id, attendance_date=salon.date.today()))
            salon.db.session.commit()
            ids = (customer.id, service.id, staff.id)

        assert client.post(f"/customers/delete/{ids[0]}").status_code == 302
        assert client.post(f"/services/delete/{ids[1]}").status_code == 302
        assert client.post(f"/staff/delete/{ids[2]}").status_code == 302

        with salon.app.app_context():
            assert salon.Customer.query.get(ids[0]) is not None
            assert salon.Service.query.get(ids[1]) is not None
            assert salon.Staff.query.get(ids[2]) is not None


def test_report_uses_net_paid_revenue_and_partial_balance():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        with salon.app.app_context():
            customer = salon.Customer.query.first()
            service = salon.Service.query.first()
            staff = salon.Staff.query.first()
            appt = salon.Appointment(
                customer_id=customer.id,
                service_id=service.id,
                staff_id=staff.id,
                appointment_date=salon.date.today(),
                appointment_time="12:00",
                status="Completed",
            )
            salon.db.session.add(appt)
            salon.db.session.flush()
            invoice = salon.Invoice(
                appointment_id=appt.id,
                customer_id=customer.id,
                amount=100,
                discount=0,
                tax=5,
                total=105,
                payment_status="Partial",
            )
            salon.db.session.add(invoice)
            salon.db.session.flush()
            salon.db.session.add(salon.InvoiceItem(invoice_id=invoice.id, description=service.name, quantity=1, unit_price=100, total=100))
            salon.db.session.add(salon.InvoicePayment(invoice_id=invoice.id, amount=40, payment_method="Cash"))
            salon.db.session.commit()

        response = client.get("/reports")
        assert response.status_code == 200
        assert b"\xe2\x82\xb940.00" in response.data or b"40" in response.data

        with salon.app.app_context():
            assert salon.invoice_net_paid_amount(salon.Invoice.query.first()) == 40
            assert salon.invoice_balance(salon.Invoice.query.first()) == 65


def test_post_forms_include_csrf_tokens_on_main_pages():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        for path in ["/customers", "/services", "/staff", "/appointments", "/inventory", "/attendance", "/staff/1/performance"]:
            response = client.get(path)
            assert response.status_code == 200, path
            if b'method="POST"' in response.data:
                assert b'name="_csrf_token"' in response.data, path


def test_refunded_invoice_has_zero_outstanding_balance():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        with salon.app.app_context():
            customer = salon.Customer.query.first()
            service = salon.Service.query.first()
            staff = salon.Staff.query.first()
            appt = salon.Appointment(customer_id=customer.id, service_id=service.id, staff_id=staff.id,
                                     appointment_date=salon.date.today(), appointment_time="13:00", status="Completed")
            salon.db.session.add(appt); salon.db.session.flush()
            invoice = salon.Invoice(appointment_id=appt.id, customer_id=customer.id, amount=100, discount=0,
                                    tax=5, total=105, payment_status="Refunded")
            salon.db.session.add(invoice); salon.db.session.commit()
            assert salon.invoice_balance(invoice) == 0.0


def test_editing_appointment_to_completed_creates_invoice():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        with salon.app.app_context():
            customer = salon.Customer.query.first()
            service = salon.Service.query.first()
            staff = salon.Staff.query.first()
            appt = salon.Appointment(customer_id=customer.id, service_id=service.id, staff_id=staff.id,
                                     appointment_date=salon.date.today(), appointment_time="14:00", status="Scheduled")
            salon.db.session.add(appt); salon.db.session.commit(); appt_id = appt.id
        response = client.post(f"/appointments/edit/{appt_id}", data={
            "customer_id": "1", "staff_id": "1", "service_id": "1",
            "appointment_date": salon.date.today().isoformat(), "appointment_time": "14:00",
            "status": "Completed", "notes": "",
        })
        assert response.status_code == 302
        with salon.app.app_context():
            invoice = salon.Invoice.query.filter_by(appointment_id=appt_id).first()
            assert invoice is not None
            assert invoice.payment_status == "Pending"


def test_internal_booking_respects_closed_hours():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        with salon.app.app_context():
            salon.db.session.add(salon.SalonHours(day_of_week=salon.date.today().weekday(), open_time="10:00", close_time="18:00", is_closed=False))
            salon.db.session.commit()
        response = client.post("/appointments/add", data={
            "customer_id": "1", "staff_id": "1", "service_id": "1",
            "appointment_date": salon.date.today().isoformat(), "appointment_time": "09:00",
        })
        assert response.status_code == 302
        with salon.app.app_context():
            assert salon.Appointment.query.count() == 0


def test_public_booking_page_renders_for_logged_out_users():
    setup_database()
    with salon.app.test_client() as client:
        response = client.get("/book")
        assert response.status_code == 200
        assert b"Book your visit" in response.data
        assert b'name="service_id"' in response.data
        assert b'name="staff_id"' in response.data


def test_settings_persists_business_hours():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        response = client.post(
            "/settings",
            data={
                "salon_name": "Audit Salon",
                "phone": "9999999999",
                "address": "Test Address",
                "tax_rate": "5",
                "loyalty_rate": "1",
                "reminder_days": "2",
                "open_0": "10:00",
                "close_0": "18:00",
                "open_1": "09:30",
                "close_1": "19:00",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        with salon.app.app_context():
            monday = salon.SalonHours.query.filter_by(day_of_week=0).first()
            tuesday = salon.SalonHours.query.filter_by(day_of_week=1).first()
            assert monday is not None
            assert monday.open_time == "10:00"
            assert monday.close_time == "18:00"
            assert tuesday is not None
            assert tuesday.open_time == "09:30"
            assert tuesday.close_time == "19:00"
            assert salon.SalonHours.query.count() == 7


def test_default_business_hours_are_initialized_and_enforced():
    setup_database()
    with salon.app.app_context():
        salon.init_db()
        assert salon.SalonHours.query.count() == 7
        service = salon.Service.query.first()
        staff = salon.Staff.query.first()
        today = salon.date.today()
        future_weekday = today
        for _ in range(7):
            if salon.SalonHours.query.filter_by(day_of_week=future_weekday.weekday()).first():
                break
            future_weekday += salon.timedelta(days=1)
    with salon.app.test_client() as client:
        response = client.post(
            "/book",
            data={
                "name": "Outside Hours",
                "phone": "8888880000",
                "service_id": service.id,
                "staff_id": staff.id,
                "appointment_date": future_weekday.isoformat(),
                "appointment_time": "08:00",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Bookings are available" in response.data


def test_loyalty_rate_is_points_per_hundred():
    setup_database()
    with salon.app.app_context():
        setting = salon.SalonSetting(tax_rate=5, loyalty_rate=1, reminder_days=1)
        salon.db.session.add(setting)
        salon.db.session.flush()
        customer = salon.Customer.query.first()
        invoice = salon.Invoice(customer_id=customer.id, amount=500, discount=0, tax=0, total=500, payment_status="Paid")
        salon.db.session.add(invoice)
        salon.db.session.flush()
        salon.award_loyalty_for_invoice(invoice)
        salon.db.session.commit()
        loyalty = salon.CustomerLoyalty.query.filter_by(customer_id=customer.id).first()
        assert loyalty.points == 5
        assert loyalty.lifetime_spend == 500


def test_paid_invoice_cannot_receive_new_inventory_items():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        with salon.app.app_context():
            customer = salon.Customer.query.first()
            service = salon.Service.query.first()
            staff = salon.Staff.query.first()
            item = salon.InventoryItem.query.first()
            appt = salon.Appointment(
                customer_id=customer.id, staff_id=staff.id, service_id=service.id,
                appointment_date=salon.date.today(), appointment_time="15:00", status="Completed"
            )
            salon.db.session.add(appt)
            salon.db.session.flush()
            invoice = salon.Invoice(
                appointment_id=appt.id, customer_id=customer.id,
                amount=100, discount=0, tax=5, total=105, payment_status="Paid"
            )
            salon.db.session.add(invoice)
            salon.db.session.flush()
            salon.db.session.add(salon.InvoiceItem(
                invoice_id=invoice.id, description=service.name, quantity=1, unit_price=100, total=100
            ))
            salon.db.session.add(salon.InvoicePayment(
                invoice_id=invoice.id, amount=105, payment_method="Cash"
            ))
            salon.db.session.commit()
            invoice_id, item_id = invoice.id, item.id
            starting_stock = item.stock_qty
        response = client.post(
            f"/invoices/{invoice_id}/inventory-sale",
            data={"inventory_item_id": item_id, "quantity": "1"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"cannot receive new products" in response.data
        with salon.app.app_context():
            assert salon.InventoryItem.query.get(item_id).stock_qty == starting_stock
            assert salon.InventorySale.query.filter_by(invoice_id=invoice_id).count() == 0


def test_refunding_partially_paid_invoice_preserves_unpaid_balance():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        with salon.app.app_context():
            customer = salon.Customer.query.first()
            service = salon.Service.query.first()
            staff = salon.Staff.query.first()
            item = salon.InventoryItem.query.first()
            appt = salon.Appointment(
                customer_id=customer.id, staff_id=staff.id, service_id=service.id,
                appointment_date=salon.date.today(), appointment_time="16:00", status="Completed"
            )
            salon.db.session.add(appt)
            salon.db.session.flush()
            invoice = salon.Invoice(
                appointment_id=appt.id, customer_id=customer.id,
                amount=1000, discount=0, tax=0, total=1000, payment_status="Partial"
            )
            salon.db.session.add(invoice)
            salon.db.session.flush()
            salon.db.session.add(salon.InvoiceItem(
                invoice_id=invoice.id, description=service.name, quantity=1, unit_price=1000, total=1000
            ))
            salon.db.session.add(salon.InvoicePayment(
                invoice_id=invoice.id, amount=500, payment_method="Cash"
            ))
            salon.db.session.commit()
            invoice_id = invoice.id
            starting_stock = item.stock_qty
        # No product sale is linked here; this checks financial state only.
        response = client.post(
            f"/invoices/refund/{invoice_id}",
            data={"amount": "500", "refund_method": "Cash", "reason": "Customer refund"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        with salon.app.app_context():
            invoice = salon.Invoice.query.get(invoice_id)
            assert invoice.payment_status == "Pending"
            assert salon.invoice_balance(invoice) == 1000
            assert salon.InvoiceRefund.query.filter_by(invoice_id=invoice_id).count() == 1
            assert salon.InventoryItem.query.first().stock_qty == starting_stock
