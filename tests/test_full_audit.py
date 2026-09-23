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
