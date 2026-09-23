import os
from datetime import date, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/salon_ci_upgrade_audit.db"
os.environ["SALON_PRO_SECRET_KEY"] = "test-secret"
os.environ["SALON_PRO_ADMIN_PASSWORD"] = "test-admin-password"
os.environ["SALON_PRO_AUTO_CREATE_DB"] = "1"

import app as salon


def setup_database():
    salon.app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=os.environ["DATABASE_URL"],
        WTF_CSRF_ENABLED=False,
    )
    with salon.app.app_context():
        salon.db.session.remove()
        salon.db.drop_all()
        salon.db.create_all()
        salon.db.session.add(
            salon.User(
                username="admin",
                password_hash=salon.generate_password_hash("admin123"),
                role="admin",
            )
        )
        salon.db.session.add(
            salon.SalonSetting(
                salon_name="Audit Salon",
                phone="9876543210",
                address="Test Street",
                tax_rate=5,
                loyalty_rate=1,
                reminder_days=7,
            )
        )
        salon.db.session.add(
            salon.Customer(
                name="Audit Customer",
                phone="9999999999",
                date_of_birth=date(1990, 9, 25),
                anniversary_date=date(2015, 9, 26),
            )
        )
        salon.db.session.add(
            salon.Service(
                name="Audit Haircut",
                duration_minutes=30,
                price=100,
                category="Hair",
                is_active=True,
            )
        )
        salon.db.session.add(
            salon.Staff(
                name="Audit Stylist",
                phone="9888888888",
                specialty="Hair",
                is_active=True,
            )
        )
        salon.db.session.add(
            salon.InventoryItem(
                name="Audit Shampoo",
                sku="AUDIT-UPGRADE-1",
                stock_qty=10,
                reorder_level=2,
                cost_price=20,
                sale_price=50,
                is_active=True,
            )
        )
        salon.db.session.commit()


def login(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Today at a glance" in response.data


def ids():
    with salon.app.app_context():
        return (
            salon.Customer.query.first().id,
            salon.Service.query.first().id,
            salon.Staff.query.first().id,
            salon.InventoryItem.query.first().id,
        )


def test_upgrade_routes_render_and_fast_checkout_is_atomic():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        for path in [
            "/appointments",
            "/calendar?view=day",
            "/calendar?view=week",
            "/calendar?view=month",
            "/customers",
            "/quick-sale",
            "/payments",
            "/money-center",
            "/inventory",
            "/inventory/transactions",
            "/suppliers",
            "/purchases",
            "/staff/performance",
            "/reminders",
            "/packages",
            "/reports",
        ]:
            response = client.get(path)
            assert response.status_code == 200, path

        customer_id, service_id, staff_id, _ = ids()
        response = client.post(
            "/quick-sale",
            data={
                "customer_id": customer_id,
                "service_id": service_id,
                "staff_id": staff_id,
                "discount": "10",
                "tip": "5",
                "payment_method": "UPI",
                "paid_amount": "99.50",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

        with salon.app.app_context():
            invoice = salon.Invoice.query.order_by(salon.Invoice.id.desc()).first()
            assert invoice.payment_status == "Paid"
            assert round(invoice.total, 2) == 99.5
            assert salon.InvoicePayment.query.filter_by(invoice_id=invoice.id).count() == 1
            assert salon.Appointment.query.filter_by(id=invoice.appointment_id, status="Completed").count() == 1
            loyalty = salon.CustomerLoyalty.query.filter_by(customer_id=customer_id).first()
            assert loyalty is not None
            assert loyalty.points > 0


def test_invoice_template_helper_and_payment_refund_lifecycle():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        customer_id, service_id, staff_id, _ = ids()
        with salon.app.app_context():
            appointment = salon.Appointment(
                customer_id=customer_id,
                staff_id=staff_id,
                service_id=service_id,
                appointment_date=date.today(),
                appointment_time="12:00",
                status="Scheduled",
            )
            salon.db.session.add(appointment)
            salon.db.session.flush()
            invoice = salon.Invoice(
                appointment_id=appointment.id,
                customer_id=customer_id,
                amount=100,
                discount=0,
                tax=5,
                tip=5,
                total=110,
                payment_status="Pending",
                payment_method="Cash",
            )
            salon.db.session.add(invoice)
            salon.db.session.flush()
            salon.db.session.add(
                salon.InvoiceItem(
                    invoice_id=invoice.id,
                    description="Audit Haircut",
                    quantity=1,
                    unit_price=100,
                    total=100,
                )
            )
            salon.db.session.commit()
            invoice_id = invoice.id

        response = client.get(f"/invoices/{invoice_id}")
        assert response.status_code == 200
        assert b"Balance" in response.data

        response = client.post(
            f"/invoices/pay/{invoice_id}",
            data={"amount": "50", "payment_method": "Cash"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            invoice = salon.db.session.get(salon.Invoice, invoice_id)
            assert invoice.payment_status == "Partial"
            assert round(salon.invoice_balance(invoice), 2) == 60

        response = client.post(
            f"/invoices/pay/{invoice_id}",
            data={"amount": "60", "payment_method": "UPI"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            invoice = salon.db.session.get(salon.Invoice, invoice_id)
            assert invoice.payment_status == "Paid"
            assert round(salon.invoice_net_paid_amount(invoice), 2) == 110

        response = client.post(
            f"/invoices/refund/{invoice_id}",
            data={"amount": "20", "refund_method": "Cash", "reason": "Audit"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            invoice = salon.db.session.get(salon.Invoice, invoice_id)
            assert round(salon.invoice_net_paid_amount(invoice), 2) == 90
            assert round(salon.invoice_balance(invoice), 2) == 20


def test_public_booking_uses_active_conflict_status_and_staff_constraints():
    setup_database()
    with salon.app.test_client() as client:
        customer_id, service_id, staff_id, _ = ids()
        with salon.app.app_context():
            existing = salon.Appointment(
                customer_id=customer_id,
                staff_id=staff_id,
                service_id=service_id,
                appointment_date=date.today(),
                appointment_time="14:00",
                status="Scheduled",
            )
            salon.db.session.add(existing)
            salon.db.session.add(
                salon.StaffBreak(
                    staff_id=staff_id,
                    day_of_week=date.today().weekday(),
                    start_time="15:00",
                    end_time="15:30",
                    is_active=True,
                )
            )
            salon.db.session.commit()
            existing.status = "Confirmed"
            salon.db.session.commit()

        before = None
        with salon.app.app_context():
            before = salon.Appointment.query.count()

        response = client.post(
            "/book",
            data={
                "name": "Online Customer",
                "phone": "9888777666",
                "service_id": service_id,
                "staff_id": staff_id,
                "appointment_date": date.today().isoformat(),
                "appointment_time": "14:00",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            assert salon.Appointment.query.count() == before

        response = client.post(
            "/book",
            data={
                "name": "Break Customer",
                "phone": "9777666555",
                "service_id": service_id,
                "staff_id": staff_id,
                "appointment_date": date.today().isoformat(),
                "appointment_time": "15:05",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            assert salon.Appointment.query.count() == before


def test_calendar_move_and_staff_availability_endpoints():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        customer_id, service_id, staff_id, _ = ids()
        target = date.today() + timedelta(days=1)
        with salon.app.app_context():
            salon.db.session.add(
                salon.StaffSchedule(
                    staff_id=staff_id,
                    day_of_week=target.weekday(),
                    start_time="10:00",
                    end_time="18:00",
                    is_working=True,
                )
            )
            appointment = salon.Appointment(
                customer_id=customer_id,
                staff_id=staff_id,
                service_id=service_id,
                appointment_date=target,
                appointment_time="11:00",
                status="Scheduled",
            )
            salon.db.session.add(appointment)
            salon.db.session.commit()
            appointment_id = appointment.id

        response = client.get(f"/api/staff/{staff_id}/availability?date={target.isoformat()}")
        assert response.status_code == 200
        availability = response.get_json()
        assert any(
            row["day_of_week"] == target.weekday()
            and row["start_time"] == "10:00"
            and row["end_time"] == "18:00"
            and row["is_working"] is True
            for row in availability["availability"]
        )

        response = client.get(f"/api/staff/{staff_id}/breaks?date={target.isoformat()}")
        assert response.status_code == 200

        response = client.post(
            "/appointments/move",
            data={
                "appointment_id": appointment_id,
                "appointment_date": target.isoformat(),
                "appointment_time": "19:00",
            },
        )
        assert response.status_code == 400

        response = client.post(
            "/appointments/move",
            data={
                "appointment_id": appointment_id,
                "appointment_date": target.isoformat(),
                "appointment_time": "12:00",
            },
        )
        assert response.status_code == 200
        assert response.get_json()["ok"] is True


def test_packages_retention_inventory_staff_and_backup():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        customer_id, _, staff_id, item_id = ids()

        response = client.post(
            "/packages/add",
            data={
                "name": "Audit Membership",
                "package_type": "Membership",
                "price": "300",
                "total_uses": "3",
                "validity_days": "30",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

        with salon.app.app_context():
            package = salon.SalonPackage.query.first()
            package_id = package.id

        response = client.post(
            "/packages/sell",
            data={
                "customer_id": customer_id,
                "package_id": package_id,
                "payment_method": "Cash",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

        with salon.app.app_context():
            row = salon.CustomerPackage.query.first()
            assert row.status == "Active"
            package_customer_id = row.id

        response = client.post(f"/packages/use/{package_customer_id}", follow_redirects=False)
        assert response.status_code == 302

        with salon.app.app_context():
            row = salon.db.session.get(salon.CustomerPackage, package_customer_id)
            assert row.uses_used == 1

        response = client.post(
            "/purchases/add",
            data={
                "inventory_item_id": item_id,
                "quantity": "2",
                "unit_cost": "25",
                "purchase_date": date.today().isoformat(),
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

        with salon.app.app_context():
            item = salon.db.session.get(salon.InventoryItem, item_id)
            assert item.stock_qty == 12

        response = client.get("/backup/download")
        assert response.status_code == 200
        assert response.data[:2] == b"\x1f\x8b"

        response = client.get("/health")
        assert response.status_code == 200
        assert response.get_json()["database"] == "ok"
