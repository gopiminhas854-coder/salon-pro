import os
from datetime import date

os.environ["DATABASE_URL"] = "sqlite:////tmp/salon_ci_acceptance.db"
os.environ["SALON_PRO_SECRET_KEY"] = "test-secret"
os.environ["SALON_PRO_ADMIN_PASSWORD"] = "test-admin-password"
os.environ["SALON_PRO_AUTO_CREATE_DB"] = "1"

import app as salon


def setup_acceptance_database():
    salon.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=os.environ["DATABASE_URL"])
    with salon.app.app_context():
        salon.db.session.remove()
        salon.db.drop_all()
        salon.db.create_all()
        admin = salon.User(
            username="acceptance-admin",
            password_hash=salon.generate_password_hash("acceptance-password"),
            role="admin",
        )
        customer = salon.Customer(name="Acceptance Customer", phone="8888800000")
        service = salon.Service(
            name="Acceptance Haircut",
            duration_minutes=30,
            price=100,
            category="Hair",
            is_active=True,
        )
        staff = salon.Staff(name="Acceptance Stylist", is_active=True)
        item = salon.InventoryItem(
            name="Acceptance Shampoo",
            sku="ACCEPT-1",
            stock_qty=10,
            reorder_level=2,
            cost_price=20,
            sale_price=50,
            is_active=True,
        )
        salon.db.session.add_all([admin, customer, service, staff, item])
        salon.db.session.commit()
        return customer.id, service.id, staff.id, item.id


def acceptance_login(client):
    response = client.post(
        "/login",
        data={"username": "acceptance-admin", "password": "acceptance-password"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    return response


def test_customer_acceptance_flow_covers_auth_booking_billing_refund_inventory_and_session():
    customer_id, service_id, staff_id, item_id = setup_acceptance_database()

    with salon.app.test_client() as client:
        # Login/authentication.
        acceptance_login(client)

        # Core dashboard/routes required by the production workflow.
        for path in ["/", "/appointments", "/invoices", "/inventory"]:
            response = client.get(path)
            assert response.status_code == 200, path

        # Create appointment.
        response = client.post(
            "/appointments/add",
            data={
                "customer_id": str(customer_id),
                "staff_id": str(staff_id),
                "service_id": str(service_id),
                "appointment_date": date.today().isoformat(),
                "appointment_time": "10:00",
                "notes": "Acceptance test",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

        with salon.app.app_context():
            appointment = salon.Appointment.query.order_by(salon.Appointment.id.desc()).first()
            assert appointment is not None
            assert appointment.status == "Scheduled"
            appointment_id = appointment.id

        # Complete appointment and verify invoice generation.
        response = client.post(
            f"/appointments/status/{appointment_id}/Completed",
            follow_redirects=False,
        )
        assert response.status_code == 302

        with salon.app.app_context():
            appointment = salon.db.session.get(salon.Appointment, appointment_id)
            invoice = salon.Invoice.query.filter_by(appointment_id=appointment_id).first()
            assert appointment.status == "Completed"
            assert invoice is not None
            assert invoice.payment_status == "Pending"
            assert round(invoice.total, 2) == 105.0
            invoice_id = invoice.id
            starting_stock = salon.InventoryItem.query.get(item_id).stock_qty

        # Add retail inventory to the open invoice, then verify stock deduction.
        response = client.post(
            f"/invoices/{invoice_id}/inventory-sale",
            data={"inventory_item_id": str(item_id), "quantity": "2"},
            follow_redirects=False,
        )
        assert response.status_code == 302

        with salon.app.app_context():
            item = salon.InventoryItem.query.get(item_id)
            invoice = salon.Invoice.query.get(invoice_id)
            assert round(item.stock_qty, 2) == round(starting_stock - 2, 2)
            assert len(invoice.items) == 2
            assert round(invoice.total, 2) == 210.0

        # Pay the invoice in full.
        response = client.post(
            f"/invoices/pay/{invoice_id}",
            data={"amount": "210.00", "payment_method": "Cash"},
            follow_redirects=False,
        )
        assert response.status_code == 302

        with salon.app.app_context():
            invoice = salon.Invoice.query.get(invoice_id)
            assert invoice.payment_status == "Paid"
            assert round(salon.invoice_balance(invoice), 2) == 0.0
            assert round(salon.invoice_paid_amount(invoice), 2) == 210.0

        # Full refund must close the invoice and restore retail inventory.
        response = client.post(
            f"/invoices/refund/{invoice_id}",
            data={"amount": "210.00", "refund_method": "Cash", "reason": "Acceptance test"},
            follow_redirects=False,
        )
        assert response.status_code == 302

        with salon.app.app_context():
            invoice = salon.Invoice.query.get(invoice_id)
            item = salon.InventoryItem.query.get(item_id)
            assert invoice.payment_status == "Refunded"
            assert salon.invoice_balance(invoice) == 0.0
            assert round(salon.invoice_refunded_amount(invoice), 2) == 210.0
            assert round(item.stock_qty, 2) == round(starting_stock, 2)

        # Logout must clear the session, and login must work again cleanly.
        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login")

        response = client.get("/")
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login")

        acceptance_login(client)
        assert client.get("/").status_code == 200

        # Data must survive a full logout/login cycle. Logout clears only the
        # authentication session; it must never remove salon records, services,
        # invoices, payments, or revenue history.
        with salon.app.app_context():
            persisted_service = salon.Service(
                name="Smoothing Treatment",
                duration_minutes=120,
                price=3500,
                category="Hair",
                is_active=True,
            )
            salon.db.session.add(persisted_service)
            salon.db.session.flush()

            persisted_appointment = salon.Appointment(
                customer_id=customer_id,
                service_id=persisted_service.id,
                staff_id=staff_id,
                appointment_date=date.today(),
                appointment_time="18:00",
                status="Completed",
                notes="Persistence regression",
            )
            salon.db.session.add(persisted_appointment)
            salon.db.session.flush()

            persisted_invoice = salon.Invoice(
                appointment_id=persisted_appointment.id,
                customer_id=customer_id,
                amount=3500,
                discount=0,
                tax=175,
                tip=0,
                total=3675,
                payment_status="Paid",
                payment_method="UPI",
            )
            salon.db.session.add(persisted_invoice)
            salon.db.session.flush()
            salon.db.session.add(
                salon.InvoiceItem(
                    invoice_id=persisted_invoice.id,
                    description=persisted_service.name,
                    quantity=1,
                    unit_price=3500,
                    total=3500,
                )
            )
            salon.db.session.add(
                salon.InvoicePayment(
                    invoice_id=persisted_invoice.id,
                    amount=3675,
                    payment_method="UPI",
                )
            )
            salon.db.session.commit()
            persisted_service_id = persisted_service.id
            persisted_invoice_id = persisted_invoice.id
            persisted_payment = salon.InvoicePayment.query.filter_by(invoice_id=persisted_invoice.id).first()
            assert persisted_payment is not None
            assert persisted_payment.account_id == persisted_invoice.account_id

        with salon.app.app_context():
            persisted_invoice = salon.Invoice.query.get(persisted_invoice_id)
            assert persisted_invoice is not None
            assert persisted_invoice.payment_status == "Paid"
            assert round(salon.invoice_paid_amount(persisted_invoice), 2) == 3675.0

        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 302

        with salon.app.test_client() as relogin_client:
            acceptance_login(relogin_client)
            assert relogin_client.get("/").status_code == 200
            services_page = relogin_client.get("/services")
            assert services_page.status_code == 200
            assert b"Smoothing Treatment" in services_page.data

            invoices_page = relogin_client.get("/invoices")
            assert invoices_page.status_code == 200
            assert b"3,675" in invoices_page.data or b"3675" in invoices_page.data

        with salon.app.app_context():
            assert salon.db.session.get(salon.Service, persisted_service_id) is not None
            restored_invoice = salon.db.session.get(salon.Invoice, persisted_invoice_id)
            assert restored_invoice is not None
            assert restored_invoice.payment_status == "Paid"
            assert round(salon.invoice_paid_amount(restored_invoice), 2) == 3675.0
            assert round(
                salon.db.session.execute(
                    salon.db.select(salon.InvoicePayment.amount)
                    .where(salon.InvoicePayment.invoice_id == persisted_invoice_id)
                ).scalar_one(),
                2,
            ) == 3675.0


def test_production_requires_durable_postgresql_database(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    with salon.app.app_context():
        try:
            salon.assert_production_database_is_durable()
        except RuntimeError as exc:
            assert "durable PostgreSQL" in str(exc)
        else:
            raise AssertionError("Production SQLite must be rejected as non-durable")


def test_android_webview_has_explicit_main_frame_network_error_handling():
    with open("android/app/src/main/java/com/salonpro/app/MainActivity.kt", encoding="utf-8") as handle:
        source = handle.read()
    assert 'override fun onReceivedError(' in source
    assert 'request?.isForMainFrame == true' in source
    assert 'Salon Pro could not connect' in source
    assert 'Retry Salon Pro' in source
