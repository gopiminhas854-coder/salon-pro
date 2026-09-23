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
        assert response.status_code == 409

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


def test_all_fixed_get_routes_render_without_server_errors():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        checked = 0
        for rule in salon.app.url_map.iter_rules():
            if 'GET' not in rule.methods or rule.endpoint == 'static' or '<' in rule.rule:
                continue
            response = client.get(rule.rule)
            assert response.status_code < 500, f"{rule.endpoint} {rule.rule}: {response.status_code}"
            checked += 1
        assert checked >= 40


def test_command_center_crm_retention_growth_tools():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        for path in ["/insights", "/assistant", "/gift-cards", "/whatsapp/templates", "/audit-log"]:
            response = client.get(path)
            assert response.status_code == 200, path

        customer_id, service_id, staff_id, _ = ids()
        with salon.app.app_context():
            service = salon.db.session.get(salon.Service, service_id)
            service.retention_min_days = 14
            service.retention_max_days = 30
            past = salon.date.today() - salon.timedelta(days=31)
            appt = salon.Appointment(
                customer_id=customer_id, staff_id=staff_id, service_id=service_id,
                appointment_date=past, appointment_time="10:00", status="Completed"
            )
            salon.db.session.add(appt)
            salon.db.session.commit()

        response = client.get("/")
        assert response.status_code == 200
        assert b"AI Priority Panel" in response.data
        assert b"Customers arriving next" in response.data

        response = client.get("/reminders")
        assert response.status_code == 200
        assert b"31 days since last visit" in response.data
        assert b"follow-up 14" in response.data

        response = client.post(
            "/services/edit/" + str(service_id),
            data={
                "name": "Audit Haircut",
                "duration_minutes": "30",
                "price": "100",
                "category": "Hair",
                "retention_min_days": "10",
                "retention_max_days": "25",
                "is_active": "on",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            service = salon.db.session.get(salon.Service, service_id)
            assert service.retention_min_days == 10
            assert service.retention_max_days == 25

        response = client.post(
            "/gift-cards",
            data={"customer_id": customer_id, "amount": "1000", "recipient_name": "Gift User"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            card = salon.GiftCard.query.first()
            assert card is not None
            assert card.balance == 1000
            card_id = card.id

        response = client.post(
            f"/gift-cards/redeem/{card_id}",
            data={"amount": "250"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            card = salon.db.session.get(salon.GiftCard, card_id)
            assert card.balance == 750

        response = client.post(
            "/whatsapp/templates",
            data={
                "name_1": "Return reminder",
                "body_1": "Hello {{name}}, please come back!",
                "active_1": "1",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

        response = client.get(f"/whatsapp/send/{customer_id}/return", follow_redirects=False)
        assert response.status_code == 302
        assert "wa.me" in response.headers["Location"]

        response = client.post(
            "/assistant",
            data={"question": "How much money is outstanding?"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"outstanding" in response.data.lower()


def test_waitlist_and_smart_scheduling():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        customer_id, service_id, staff_id, _ = ids()
        target = date.today() + timedelta(days=1)
        response = client.post(
            "/waitlist",
            data={
                "customer_id": customer_id,
                "service_id": service_id,
                "preferred_staff_id": staff_id,
                "preferred_date": target.isoformat(),
                "preferred_time": "14:00",
                "notes": "Flexible if earlier",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            row = salon.WaitlistEntry.query.first()
            assert row is not None and row.status == "Open"
            row_id = row.id

        response = client.get("/smart-schedule", query_string={
            "service_id": service_id, "staff_id": staff_id, "date": target.isoformat()
        })
        assert response.status_code == 200
        assert b"Find an earliest slot" in response.data

        response = client.get("/api/smart-schedule", query_string={
            "service_id": service_id, "staff_id": staff_id, "date": target.isoformat()
        })
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["ok"] is True
        assert payload["slots"]

        slot = payload["slots"][0]
        response = client.post(
            f"/waitlist/{row_id}/book",
            data={"appointment_date": slot["date"], "appointment_time": slot["time"], "staff_id": slot["staff_id"]},
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            row = salon.db.session.get(salon.WaitlistEntry, row_id)
            assert row.status == "Booked"
            assert salon.Appointment.query.filter_by(
                customer_id=customer_id, service_id=service_id, appointment_date=target,
                appointment_time=slot["time"], status="Confirmed"
            ).count() == 1


def test_role_permissions_and_backup_history():
    setup_database()
    with salon.app.app_context():
        staff_row = salon.Staff.query.first()
        manager = salon.User(username="manager", password_hash=salon.generate_password_hash("manager123"), role="manager")
        receptionist = salon.User(username="reception", password_hash=salon.generate_password_hash("reception123"), role="receptionist")
        salon.db.session.add_all([manager, receptionist])
        salon.db.session.commit()
        manager_id = manager.id
        receptionist_id = receptionist.id

    with salon.app.test_client() as client:
        response = client.post("/login", data={"username": "manager", "password": "manager123"}, follow_redirects=True)
        assert response.status_code == 200
        assert client.get("/insights").status_code == 200
        assert client.get("/settings").status_code == 200 or client.get("/settings").status_code == 302
        with salon.app.app_context():
            salon.db.session.add(salon.User(username="manager2", password_hash=salon.generate_password_hash("manager234"), role="manager"))
            salon.db.session.commit()
        assert client.get("/backup-center").status_code == 302

    with salon.app.test_client() as client:
        response = client.post("/login", data={"username": "reception", "password": "reception123"}, follow_redirects=True)
        assert response.status_code == 200
        assert client.get("/insights").status_code == 302
        assert client.get("/money-center").status_code == 302

    with salon.app.test_client() as client:
        login(client)
        response = client.get("/backup-center")
        assert response.status_code == 200
        response = client.get("/backup/download")
        assert response.status_code == 200
        with salon.app.app_context():
            log = salon.BackupLog.query.order_by(salon.BackupLog.id.desc()).first()
            assert log is not None
            assert log.size_bytes > 0


def test_gift_card_can_pay_invoice():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        customer_id, service_id, staff_id, _ = ids()
        with salon.app.app_context():
            appointment = salon.Appointment(
                customer_id=customer_id, staff_id=staff_id, service_id=service_id,
                appointment_date=date.today(), appointment_time="13:00", status="Completed"
            )
            salon.db.session.add(appointment)
            salon.db.session.flush()
            invoice = salon.Invoice(
                appointment_id=appointment.id, customer_id=customer_id,
                amount=100, discount=0, tax=0, total=100, payment_status="Pending"
            )
            salon.db.session.add(invoice)
            salon.db.session.flush()
            salon.db.session.add(salon.InvoiceItem(
                invoice_id=invoice.id, description="Audit Haircut", quantity=1, unit_price=100, total=100
            ))
            card = salon.GiftCard(code="TEST-GC-1000", purchaser_customer_id=customer_id, original_amount=1000, balance=1000, status="Active")
            salon.db.session.add(card)
            salon.db.session.commit()
            invoice_id, card_id = invoice.id, card.id

        response = client.post(
            f"/invoices/pay/{invoice_id}",
            data={"amount": "100", "payment_method": "Gift Card", "gift_card_code": "TEST-GC-1000"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        with salon.app.app_context():
            invoice = salon.db.session.get(salon.Invoice, invoice_id)
            card = salon.db.session.get(salon.GiftCard, card_id)
            assert invoice.payment_status == "Paid"
            assert card.balance == 900
            assert salon.GiftCardTransaction.query.filter_by(gift_card_id=card_id, invoice_id=invoice_id, transaction_type="Redeem").count() == 1
