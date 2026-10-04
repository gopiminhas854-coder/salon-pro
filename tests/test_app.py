import os
import sys
from io import BytesIO
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
        user = salon.User(username="admin", password_hash=salon.generate_password_hash("test-admin-password"), role="admin")
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
    return c.post("/login", data={"username": "admin", "password": "test-admin-password"}, follow_redirects=True)

def test_phone_number_normalization():
    assert salon.normalize_phone_number("98765 43210") == "+919876543210"
    assert salon.normalize_phone_number("09876543210") == "+919876543210"
    assert salon.normalize_phone_number("+91-98765-43210") == "+919876543210"
    assert salon.normalize_phone_number("not-a-phone") is None


def test_phone_login_requires_server_otp_configuration(client):
    c, _ = client
    response = c.post("/auth/phone/send", data={"phone": "9876543210"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Phone login is not configured yet" in response.data


def test_not_found_has_recovery_link(client):
    c, _ = client
    login(c)
    response = c.get("/this-page-does-not-exist")
    assert response.status_code == 404
    assert b"Return to Salon Pro" in response.data


def test_health_and_login(client):
    c, salon = client
    assert c.get("/health").status_code == 200
    assert b'"status":"ok"' in c.get("/health").data
    response = login(c)
    assert response.status_code == 200
    assert b"Overview" in response.data


def test_new_signup_routes_to_199_subscription(client):
    c, salon = client
    response = c.post("/register", data={
        "business_name": "New Salon",
        "email": "owner@example.com",
        "phone": "9876543210",
        "password": "strong-password-123",
        "confirm_password": "strong-password-123",
    }, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/subscription?reason=new")

    salon.app.config.update(SALON_PRO_MONTHLY_PRICE_INR=199)
    page = c.get("/subscription")
    assert page.status_code == 200
    assert "₹199".encode() in page.data
    assert b"/month" in page.data
    assert "Subscribe &amp; Pay ₹199".encode() in page.data

def test_subscription_order_uses_19900_paise_and_owner_data(client, monkeypatch):
    c, salon = client
    response = c.post("/register", data={
        "business_name": "Paid Salon",
        "email": "paid@example.com",
        "phone": "9876543211",
        "password": "strong-password-123",
        "confirm_password": "strong-password-123",
    }, follow_redirects=False)
    assert response.status_code == 302

    salon.app.config.update(
        RAZORPAY_KEY_ID="rzp_test_key",
        RAZORPAY_KEY_SECRET="rzp_test_secret",
        SALON_PRO_MONTHLY_PRICE_INR=199,
    )

    captured = {}
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"id": "order_test_199"}

    def fake_post(url, json, auth, timeout):
        captured.update({"url": url, "json": json, "auth": auth, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(salon.requests, "post", fake_post)
    order = c.post("/subscription/order")
    assert order.status_code == 200
    payload = order.get_json()
    assert payload["ok"] is True
    assert payload["amount"] == 19900
    assert captured["json"]["amount"] == 19900
    assert captured["json"]["currency"] == "INR"
    assert captured["json"]["notes"]["plan"] == "monthly"

    with salon.app.app_context():
        sub = salon.Subscription.query.filter_by(razorpay_order_id="order_test_199").first()
        assert sub is not None
        assert sub.amount_paise == 19900

def test_subscription_payment_verification_and_webhook_are_idempotent(client, monkeypatch):
    c, salon = client
    c.post("/register", data={
        "business_name": "Verify Salon",
        "email": "verify@example.com",
        "phone": "9876543212",
        "password": "strong-password-123",
        "confirm_password": "strong-password-123",
    }, follow_redirects=False)

    salon.app.config.update(
        RAZORPAY_KEY_ID="rzp_test_key",
        RAZORPAY_KEY_SECRET="rzp_test_secret",
        RAZORPAY_WEBHOOK_SECRET="webhook_secret",
        SALON_PRO_MONTHLY_PRICE_INR=199,
    )
    with salon.app.app_context():
        user = salon.current_user()
        sub = salon.Subscription(
            user_id=user.id,
            plan_key="monthly",
            status="pending",
            amount_paise=19900,
            currency="INR",
            razorpay_order_id="order_verify_199",
        )
        salon.db.session.add(sub)
        salon.db.session.commit()

    payment_id = "pay_verify_199"
    order_id = "order_verify_199"
    signature = salon.hmac.new(
        salon.app.config["RAZORPAY_KEY_SECRET"].encode(),
        f"{order_id}|{payment_id}".encode(),
        salon.hashlib.sha256,
    ).hexdigest()

    class PaymentResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "id": payment_id,
                "order_id": order_id,
                "amount": 19900,
                "status": "captured",
            }

    monkeypatch.setattr(salon.requests, "get", lambda *args, **kwargs: PaymentResponse())
    verified = c.post("/subscription/verify", json={
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    })
    assert verified.status_code == 200
    assert verified.get_json()["ok"] is True

    with salon.app.app_context():
        sub = salon.Subscription.query.filter_by(razorpay_order_id=order_id).first()
        assert sub.status == "active"
        assert sub.expires_at is not None
        assert sub.webhook_received is False

    payload = salon.json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "order_id": order_id,
            "id": payment_id,
        }}},
    }, separators=(",", ":"))
    webhook_signature = salon.hmac.new(
        salon.app.config["RAZORPAY_WEBHOOK_SECRET"].encode(),
        payload.encode(),
        salon.hashlib.sha256,
    ).hexdigest()
    webhook = c.post(
        "/webhooks/razorpay",
        data=payload,
        content_type="application/json",
        headers={"X-Razorpay-Signature": webhook_signature},
    )
    assert webhook.status_code == 200

    with salon.app.app_context():
        sub = salon.Subscription.query.filter_by(razorpay_order_id=order_id).first()
        assert sub.status == "active"
        assert sub.webhook_received is True
        expires_at = sub.expires_at

    duplicate = c.post(
        "/webhooks/razorpay",
        data=payload,
        content_type="application/json",
        headers={"X-Razorpay-Signature": webhook_signature},
    )
    assert duplicate.status_code == 200
    with salon.app.app_context():
        sub = salon.Subscription.query.filter_by(razorpay_order_id=order_id).first()
        assert sub.expires_at == expires_at

def test_device_remember_token_restores_session(client):
    c, salon = client
    login(c)

    with salon.app.app_context():
        user = salon.User.query.filter_by(username="admin").first()
        token = salon.issue_remember_token(user)

    with c.session_transaction() as sess:
        sess.clear()

    response = c.post(
        "/auth/remember",
        headers={"X-Salon-Pro-Remember-Token": token},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["redirect"].endswith("/")
    assert payload.get("remember_token")

    with c.session_transaction() as sess:
        assert sess.get("user_id") is not None

def test_mobile_bottom_nav_keeps_all_icons_and_active_state(client):
    c, _ = client
    login(c)
    response = c.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert 'class="sp-mobile-nav" aria-label="Primary navigation"' in html
    assert 'class="sp-mobile-link active"' in html
    assert html.count('class="sp-mobile-symbol"') == 4
    assert 'class="sp-mobile-add-symbol"' in html
    assert 'aria-label="Home"' in html
    assert 'aria-label="Bookings"' in html
    assert 'aria-label="Clients"' in html
    assert 'aria-label="More"' in html



def test_login_page_has_valid_single_native_google_script(client):
    c, _ = client
    response = c.get("/login")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert html.count("const nativeButton =") == 1
    assert "const nativeButton = document.getElementById('native-google-login');\n    <script>" not in html


def test_invalid_device_remember_token_does_not_login(client):
    c, _ = client
    response = c.post(
        "/auth/remember",
        headers={"X-Salon-Pro-Remember-Token": "not-a-real-token"},
    )
    assert response.status_code == 401

def test_authenticated_session_survives_reopening_login_route(client):
    c, salon = client
    login(c)

    with c.session_transaction() as sess:
        assert sess.get("user_id") is not None
        assert sess.permanent is True

    # The Android WebView opens /login on startup. A valid session must route
    # straight back to the authenticated app instead of showing login again.
    response = c.get("/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")

    set_cookie = response.headers.get("Set-Cookie", "")
    assert "session=" in set_cookie

def test_logout_still_requires_login_after_persistent_session(client):
    c, salon = client
    login(c)
    response = c.get("/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")

    response = c.get("/login", follow_redirects=False)
    assert response.status_code == 200
    assert b"Login" in response.data or b"Sign in" in response.data

def test_logout_clears_session(client):
    c, salon = client
    login(c)
    with c.session_transaction() as sess:
        assert sess.get("user_id") is not None

    response = c.get("/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")

    with c.session_transaction() as sess:
        assert "user_id" not in sess
        assert "username" not in sess
        assert "role" not in sess


def test_colour_lab_android_webview_accepts_same_origin_form_without_fresh_token(client):
    c, salon = client
    login(c)

    # Simulate a cached Android WebView form carrying a stale token. The
    # request is still same-origin/authenticated, so a deployment must not
    # destroy the user's completed form.
    response = c.post(
        "/colour-lab/cases",
        data={
            "_csrf_token": "stale-token-from-cached-form",
            "title": "Android WebView CSRF Regression",
            "current_hair_type": "Virgin",
            "target_tone": "Honey caramel",
            "formula_json": "[]",
        },
        headers={
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 SalonProAndroid/1.0.4",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/colour-lab/cases/" in response.headers["Location"]

    with salon.app.app_context():
        case = salon.ColourCase.query.filter_by(title="Android WebView CSRF Regression").first()
        assert case is not None


def test_colour_lab_csrf_accepts_same_host_https_referer_behind_proxy(client):
    c, salon = client
    login(c)
    with c.session_transaction() as sess:
        sess['_csrf_token'] = 'server-token'
    response = c.post(
        '/colour-lab/cases',
        data={
            '_csrf_token': 'stale-token',
            'title': 'Proxy-safe colour case',
            'customer_id': '',
            'staff_id': '',
            'current_hair_type': 'Virgin',
            'current_level': '5',
            'target_level': '7',
            'technique': 'Global colour',
            'formula_json': '[]',
        },
        headers={'Referer': 'https://localhost/colour-lab'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert '/colour-lab/cases/' in response.headers['Location']


def test_colour_lab_form_has_csrf_and_case_can_be_saved(client):
    c, salon = client
    login(c)
    page = c.get("/colour-lab")
    assert page.status_code == 200
    html = page.data.decode("utf-8")
    marker = '<input type="hidden" name="_csrf_token" value="'
    assert marker in html

    with c.session_transaction() as sess:
        csrf = sess.get("_csrf_token")
    assert csrf

    response = c.post("/colour-lab/cases", data={
        "_csrf_token": csrf,
        "title": "CSRF Regression Case",
        "customer_id": "",
        "staff_id": "",
        "current_hair_type": "Virgin",
        "current_level": "6",
        "current_tone": "Golden",
        "hair_condition": "Good",
        "target_level": "7",
        "target_tone": "Honey caramel",
        "technique": "Global colour",
        "brand": "Test Brand",
        "developer": "Test Developer",
        "developer_strength": "20 vol",
        "mixing_ratio": "1:1",
        "processing_minutes": "30",
        "application_notes": "Regression test",
        "formula_json": "[]",
        "before_photo_data": "",
    }, follow_redirects=False)
    assert response.status_code == 302
    assert "/colour-lab/cases/" in response.headers["Location"]

    with salon.app.app_context():
        case = salon.ColourCase.query.filter_by(title="CSRF Regression Case").first()
        assert case is not None


def test_colour_lab_multipart_before_and_after_photos_save(client):
    c, salon = client
    login(c)

    from PIL import Image

    def jpeg_bytes():
        buf = BytesIO()
        Image.new("RGB", (1600, 1200), (96, 84, 72)).save(buf, format="JPEG", quality=92)
        buf.seek(0)
        return buf

    page = c.get("/colour-lab")
    assert page.status_code == 200
    with c.session_transaction() as sess:
        csrf = sess.get("_csrf_token")
    assert csrf

    response = c.post(
        "/colour-lab/cases",
        data={
            "_csrf_token": csrf,
            "title": "Multipart photo regression",
            "customer_id": "",
            "staff_id": "",
            "current_hair_type": "Virgin",
            "current_level": "6",
            "current_tone": "Golden",
            "hair_condition": "Good",
            "target_level": "7",
            "target_tone": "Honey caramel",
            "technique": "Global colour",
            "formula_json": "[]",
            "before_photo": (jpeg_bytes(), "before.jpg"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["Location"]
    assert "/colour-lab/cases/" in location

    case_id = int(location.rstrip("/").rsplit("/", 1)[-1])
    with salon.app.app_context():
        case = salon.ColourCase.query.get(case_id)
        assert case is not None
        assert case.before_photo_data.startswith("data:image/jpeg;base64,")
        assert len(case.before_photo_data) < 2_500_000

    response = c.post(
        f"/colour-lab/cases/{case_id}/complete",
        data={
            "_csrf_token": csrf,
            "result_rating": "Good match",
            "next_time_notes": "Keep the same formula.",
            "result_notes": "Even tone and shine.",
            "after_photo": (jpeg_bytes(), "after.jpg"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with salon.app.app_context():
        case = salon.ColourCase.query.get(case_id)
        assert case.after_photo_data.startswith("data:image/jpeg;base64,")
        assert case.result_rating == "Good match"
        assert case.next_time_notes == "Keep the same formula."


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

def test_completed_appointment_invoice_is_created_atomically(client):
    client, salon = client
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

    response = c.get(f"/api/business-intelligence?start={(salon.date.today() - salon.timedelta(days=31)).isoformat()}&end={salon.date.today().isoformat()}")
    assert response.status_code == 200
    bi = response.get_json()
    assert bi["financial"]["net_revenue"] == 210
    assert bi["financial"]["average_paid_invoice"] == 105
    assert bi["appointments"]["completion_rate"] == 100
    assert bi["customers"]["repeat_customer_rate"] == 100
    assert bi["inventory"]["stock_value_at_cost"] == 200
    assert bi["inventory"]["low_stock_items"] == 0


def test_retention_service_and_staff_intelligence(client):
    c, salon = client
    login(c)
    with salon.app.app_context():
        customer = salon.Customer.query.first()
        service = salon.Service.query.first()
        staff = salon.Staff.query.first()
        appt = salon.Appointment(customer_id=customer.id, staff_id=staff.id, service_id=service.id,
                                  appointment_date=salon.date.today() - salon.timedelta(days=10),
                                  appointment_time="10:00", status="Completed")
        salon.db.session.add(appt)
        salon.db.session.flush()
        inv = salon.Invoice(appointment_id=appt.id, customer_id=customer.id, amount=100,
                            discount=0, tax=5, total=105, payment_status="Paid")
        salon.db.session.add(inv)
        salon.db.session.flush()
        salon.db.session.add(salon.InvoiceItem(invoice_id=inv.id, description=service.name,
                                               quantity=1, unit_price=100, total=100))
        salon.db.session.add(salon.InvoicePayment(invoice_id=inv.id, amount=105, payment_method="UPI"))
        salon.db.session.commit()

    retention = c.get("/api/crm/retention")
    assert retention.status_code == 200
    data = retention.get_json()
    assert data["counts"]["active"] == 1

    services = c.get("/api/business-intelligence/services")
    assert services.status_code == 200
    service_data = services.get_json()
    row = next(x for x in service_data["services"] if x["service"] == "Test Haircut")
    assert row["completed"] == 1
    assert row["net_revenue"] == 105
    assert row["revenue_per_completed_visit"] == 105

    staff_data = c.get("/api/business-intelligence/staff?start=2000-01-01&end=2100-01-01").get_json()
    staff_row = next(x for x in staff_data["staff"] if x["staff"] == "Test Stylist")
    assert staff_row["completed"] == 1
    assert staff_row["net_revenue"] == 105
    assert staff_row["revenue_per_completed_visit"] == 105


def test_customer_milestones_and_special_reminders(client):
    c, salon = client
    today = salon.date.today()
    target = today + salon.timedelta(days=7)
    with salon.app.app_context():
        customer = salon.Customer.query.first()
        customer.date_of_birth = salon.date(today.year - 25, target.month, target.day)
        customer.anniversary_date = salon.date(today.year - 5, target.month, target.day)
        salon.db.session.commit()

    login(c)
    response = c.get("/reminders")
    assert response.status_code == 200
    assert b"Birthdays" in response.data
    assert b"Anniversaries" in response.data
    assert b"Test Customer" in response.data

def test_customer_form_saves_milestones_and_reminder_uses_saved_dates(client):
    c, salon = client
    login(c)

    target = salon.date.today() + salon.timedelta(days=7)
    response = c.post("/customers/add", data={
        "name": "Milestone Customer",
        "phone": "8888888881",
        "email": "milestone@example.com",
        "gender": "Female",
        "date_of_birth": f"{salon.date.today().year - 30:04d}-{target.month:02d}-{target.day:02d}",
        "anniversary_date": f"{salon.date.today().year - 4:04d}-{target.month:02d}-{target.day:02d}",
        "address": "Test Address",
        "notes": "Milestone test",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Customer added successfully" in response.data

    with salon.app.app_context():
        customer = salon.Customer.query.filter_by(name="Milestone Customer").one()
        assert customer.date_of_birth == salon.date(salon.date.today().year - 30, target.month, target.day)
        assert customer.anniversary_date == salon.date(salon.date.today().year - 4, target.month, target.day)

    response = c.get("/reminders")
    assert response.status_code == 200
    assert b"Milestone Customer" in response.data
    assert b"Birthdays" in response.data
    assert b"Anniversaries" in response.data


def test_dashboard_owner_metrics_and_backup(client):
    c, salon = client
    login(c)
    with salon.app.app_context():
        customer = salon.Customer.query.first()
        service = salon.Service.query.first()
        staff = salon.Staff.query.first()
        appt = salon.Appointment(
            customer_id=customer.id, staff_id=staff.id, service_id=service.id,
            appointment_date=salon.date.today(), appointment_time="15:00",
            status="Scheduled"
        )
        salon.db.session.add(appt)
        salon.db.session.flush()
        inv = salon.Invoice(
            appointment_id=appt.id, customer_id=customer.id,
            amount=100, discount=0, tax=5, total=105,
            payment_status="Pending"
        )
        salon.db.session.add(inv)
        salon.db.session.add(salon.Expense(
            title="Rent", category="Rent", amount=20,
            expense_date=salon.date.today()
        ))
        salon.db.session.commit()

    dashboard = c.get("/")
    assert dashboard.status_code == 200
    assert b"Money still to collect" in dashboard.data
    assert b"Today profit" in dashboard.data

    backup = c.get("/backup/download")
    assert backup.status_code == 200
    assert backup.mimetype == "application/gzip"
    import gzip, json
    payload = json.loads(gzip.decompress(backup.data).decode("utf-8"))
    assert payload["format"] == "salon-pro-backup"
    assert "customer" in payload["tables"]


def test_command_center_accordion_navigation(client):
    c, _ = client
    login(c)
    response = c.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert 'data-command-accordion' in html
    assert html.count('class="sp-command-section"') == 6
    assert html.count('class="sp-command-summary"') == 6
    assert html.count('sp-command-chevron') == 6
    assert 'Tap a section to open it.' in html


def test_mobile_nav_uses_ios_color_gradients(client):
    c, _ = client
    login(c)
    response = c.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert 'id="spHomeGrad"' in html
    assert 'id="spBookGrad"' in html
    assert 'id="spAddGrad"' in html
    assert 'id="spClientGrad"' in html
    assert 'id="spMoreGrad"' in html


def test_mobile_main_menu_has_outside_tap_close_behavior(client):
    c, _ = client
    login(c)
    response = c.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert 'class="sp-sidebar-backdrop" type="button" aria-label="Close navigation"' in html
    assert 'class="sp-sidebar-close" type="button" aria-label="Close navigation"' in html
    assert 'aria-controls="spSidebar"' in html
    assert "function closeSidebar()" in html
    assert "window.SalonProSidebar" in html
    assert "document.body.classList.add('sp-menu-open')" in html
    assert "document.addEventListener('pointerdown'" in html
    assert "document.addEventListener('touchstart'" in html
    assert "event.target.closest('.sp-sidebar-close')" in html
    assert "event.target.closest('.sp-sidebar-backdrop')" in html
    assert "if(isInsideSidebar(event.target)) return;" in html


def test_android_back_closes_drawer_before_exiting():
    from pathlib import Path
    path = Path("android/app/src/main/java/com/salonpro/app/MainActivity.kt")
    content = path.read_text(encoding="utf-8")
    assert "SalonProSidebar" in content
    assert "window.SalonProSidebar && window.SalonProSidebar.isOpen" in content
    assert "window.SalonProSidebar && window.SalonProSidebar.close" in content

def test_critical_customer_journey_login_signup_tenant_data_colour_and_recovery(client, monkeypatch):
    """Hard acceptance test for the owner journey from account creation to recovery."""
    legacy_client, salon = client

    # 1) Login must work before we start the new-account flow.
    response = login(legacy_client)
    assert response.status_code == 200
    with salon.app.app_context():
        legacy_user = salon.User.query.filter_by(username="admin").first()
        legacy_account = salon.AccountProfile.query.filter_by(user_id=legacy_user.id).first()
        legacy_customer = salon.Customer.query.filter_by(name="Test Customer").first()
        assert legacy_account is not None
        assert legacy_customer is not None
        legacy_account_id = legacy_account.id
        legacy_customer_id = legacy_customer.id

    # The new signup must happen from a fresh browser session. A logged-in
    # session is intentionally redirected away from /register.
    c = salon.app.test_client()

    # 2) Signup -> ₹199 subscription -> successful payment verification.
    salon.app.config.update(
        RAZORPAY_KEY_ID="rzp_test_key",
        RAZORPAY_KEY_SECRET="rzp_test_secret",
        RAZORPAY_WEBHOOK_SECRET="webhook_secret",
        SALON_PRO_MONTHLY_PRICE_INR=199,
    )

    signup = c.post("/register", data={
        "business_name": "Flow Test Salon",
        "email": "flow-owner@example.com",
        "phone": "9876543299",
        "password": "strong-password-123",
        "confirm_password": "strong-password-123",
    }, follow_redirects=False)
    assert signup.status_code == 302
    assert signup.headers["Location"].endswith("/subscription?reason=new")

    captured = {}
    class FakeOrderResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"id": "order_flow_199"}

    def fake_order_post(url, json, auth, timeout):
        captured.update({"url": url, "json": json, "auth": auth, "timeout": timeout})
        return FakeOrderResponse()

    monkeypatch.setattr(salon.requests, "post", fake_order_post)
    order = c.post("/subscription/order")
    assert order.status_code == 200
    assert order.get_json()["amount"] == 19900
    assert captured["json"]["amount"] == 19900

    payment_id = "pay_flow_199"
    order_id = "order_flow_199"
    signature = salon.hmac.new(
        salon.app.config["RAZORPAY_KEY_SECRET"].encode(),
        f"{order_id}|{payment_id}".encode(),
        salon.hashlib.sha256,
    ).hexdigest()

    class FakePaymentResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "id": payment_id,
                "order_id": order_id,
                "amount": 19900,
                "status": "captured",
            }

    monkeypatch.setattr(salon.requests, "get", lambda *args, **kwargs: FakePaymentResponse())
    verified = c.post("/subscription/verify", json={
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    })
    assert verified.status_code == 200
    assert verified.get_json()["ok"] is True

    with salon.app.app_context():
        flow_user = salon.User.query.filter_by(username="flow-owner@example.com").first()
        flow_account = salon.AccountProfile.query.filter_by(user_id=flow_user.id).first()
        assert flow_account is not None
        assert salon.Subscription.query.filter_by(
            user_id=flow_user.id, status="active"
        ).first() is not None
        flow_account_id = flow_account.id

        # Seed the new tenant with its own service/staff/product. These records
        # intentionally share the database with the legacy tenant. Use explicit
        # SQL inserts here because the fixture preserves a Flask request context;
        # the application endpoints below are what exercise the tenant write guard.
        salon.db.session.execute(salon.Service.__table__.insert().values(
            account_id=flow_account_id,
            name="Flow Colour Service",
            duration_minutes=30,
            price=100,
            category="Hair",
            is_active=True,
        ))
        salon.db.session.execute(salon.Staff.__table__.insert().values(
            account_id=flow_account_id,
            name="Flow Stylist",
            is_active=True,
        ))
        salon.db.session.execute(salon.InventoryItem.__table__.insert().values(
            account_id=flow_account_id,
            name="Flow Developer",
            sku="FLOW-1",
            stock_qty=5,
            reorder_level=1,
            cost_price=20,
            sale_price=40,
            is_active=True,
        ))
        today_weekday = salon.date.today().weekday()
        salon.db.session.execute(salon.SalonHours.__table__.insert().values(
            account_id=flow_account_id,
            day_of_week=today_weekday,
            open_time="00:00",
            close_time="23:59",
            is_closed=False,
        ))
        salon.db.session.commit()

        service_id = salon.db.session.execute(
            salon.db.select(salon.Service.id).where(
                salon.Service.account_id == flow_account_id,
                salon.Service.name == "Flow Colour Service",
            )
        ).scalar_one()
        staff_id = salon.db.session.execute(
            salon.db.select(salon.Staff.id).where(
                salon.Staff.account_id == flow_account_id,
                salon.Staff.name == "Flow Stylist",
            )
        ).scalar_one()
        item_id = salon.db.session.execute(
            salon.db.select(salon.InventoryItem.id).where(
                salon.InventoryItem.account_id == flow_account_id,
                salon.InventoryItem.sku == "FLOW-1",
            )
        ).scalar_one()

    # 3) Tenant isolation: the new salon must not see the legacy salon's data.
    dashboard = c.get("/")
    assert dashboard.status_code == 200
    customers_page = c.get("/customers")
    assert customers_page.status_code == 200
    assert b"Test Customer" not in customers_page.data

    legacy_customer_page = c.get(f"/customers/edit/{legacy_customer_id}")
    assert legacy_customer_page.status_code == 404

    # 4) Customer creation.
    customer_response = c.post("/customers/add", data={
        "name": "Flow Customer",
        "phone": "9999998888",
        "email": "flow-customer@example.com",
        "gender": "Female",
        "notes": "Original recovery note",
    }, follow_redirects=True)
    assert customer_response.status_code == 200
    assert b"Customer added successfully" in customer_response.data

    with salon.app.app_context():
        flow_customer = salon.db.session.execute(
            salon.db.select(salon.Customer).where(
                salon.Customer.account_id == flow_account_id,
                salon.Customer.name == "Flow Customer",
            )
        ).scalar_one_or_none()
        assert flow_customer is not None
        flow_customer_id = flow_customer.id

    # 5) Appointment creation.
    appointment_response = c.post("/appointments/add", data={
        "appointment_date": salon.date.today().isoformat(),
        "appointment_time": "23:00",
        "customer_id": str(flow_customer_id),
        "staff_id": str(staff_id),
        "service_id": str(service_id),
        "status": "Booked",
        "recurrence_rule": "None",
        "notes": "Critical-flow appointment",
    }, follow_redirects=True)
    assert appointment_response.status_code == 200

    with salon.app.app_context():
        appt = salon.db.session.execute(
            salon.db.select(salon.Appointment).where(
                salon.Appointment.account_id == flow_account_id,
                salon.Appointment.customer_id == flow_customer_id,
                salon.Appointment.staff_id == staff_id,
            )
        ).scalar_one_or_none()
        assert appt is not None
        appointment_id = appt.id

    # 6) Billing is created exactly once when the appointment is completed.
    completed = c.post(f"/appointments/status/{appointment_id}/Completed")
    assert completed.status_code == 302

    with salon.app.app_context():
        invoice = salon.db.session.execute(
            salon.db.select(salon.Invoice).where(
                salon.Invoice.account_id == flow_account_id,
                salon.Invoice.appointment_id == appointment_id,
            )
        ).scalar_one_or_none()
        assert invoice is not None
        assert invoice.payment_status == "Pending"
        invoice_id = invoice.id

    # 7) Stock sale + payment. Both must survive without duplicate rows.
    stock_sale = c.post(f"/invoices/{invoice_id}/inventory-sale", data={
        "inventory_item_id": str(item_id),
        "quantity": "2",
    }, follow_redirects=True)
    assert stock_sale.status_code == 200

    with salon.app.app_context():
        stock_qty = salon.db.session.execute(
            salon.db.select(salon.InventoryItem.stock_qty).where(
                salon.InventoryItem.id == item_id,
                salon.InventoryItem.account_id == flow_account_id,
            )
        ).scalar_one()
        sale_count = salon.db.session.execute(
            salon.db.select(salon.func.count(salon.InventorySale.id)).where(
                salon.InventorySale.invoice_id == invoice_id,
                salon.InventorySale.account_id == flow_account_id,
            )
        ).scalar_one()
        assert stock_qty == 3
        assert sale_count == 1

    with salon.app.app_context():
        payable_invoice = salon.db.session.execute(
            salon.db.select(salon.Invoice).where(
                salon.Invoice.id == invoice_id,
                salon.Invoice.account_id == flow_account_id,
            )
        ).scalar_one()
        payable_amount = salon.invoice_balance(payable_invoice)
        assert payable_amount > 0

    payment = c.post(f"/invoices/pay/{invoice_id}", data={
        "amount": f"{payable_amount:.2f}",
        "payment_method": "UPI",
    }, follow_redirects=True)
    assert payment.status_code == 200

    with salon.app.app_context():
        paid_invoice = salon.db.session.execute(
            salon.db.select(salon.Invoice).where(
                salon.Invoice.id == invoice_id,
                salon.Invoice.account_id == flow_account_id,
            )
        ).scalar_one()
        assert paid_invoice.payment_status == "Paid"
        assert round(salon.invoice_balance(paid_invoice), 2) == 0
        assert salon.InvoicePayment.query.filter_by(invoice_id=invoice_id).count() == 1

    # 8) Colour Lab: save a case with a real multipart before-photo.
    from PIL import Image

    def jpeg_bytes():
        buf = BytesIO()
        Image.new("RGB", (1200, 900), (96, 84, 72)).save(buf, format="JPEG", quality=90)
        buf.seek(0)
        return buf

    colour_page = c.get("/colour-lab")
    assert colour_page.status_code == 200
    csrf = None
    with c.session_transaction() as sess:
        csrf = sess.get("_csrf_token")

    colour_response = c.post("/colour-lab/cases", data={
        "_csrf_token": csrf,
        "title": "Critical Flow Colour Case",
        "customer_id": str(flow_customer_id),
        "staff_id": str(staff_id),
        "current_hair_type": "Coloured",
        "current_level": "6",
        "current_tone": "Golden",
        "hair_condition": "Good",
        "target_level": "7",
        "target_tone": "Honey caramel",
        "technique": "Global colour",
        "brand": "Flow Brand",
        "developer": "Flow Developer",
        "developer_strength": "20 vol",
        "mixing_ratio": "1:1",
        "processing_minutes": "30",
        "application_notes": "Save/reopen acceptance test",
        "formula_json": salon.json.dumps([{
            "inventory_item_id": item_id,
            "product_name": "Flow Developer",
            "brand": "Flow Brand",
            "shade_code": "7.3",
            "quantity_grams": 30,
            "developer": "20 vol",
        }]),
        "before_photo": (jpeg_bytes(), "before.jpg"),
    }, follow_redirects=False)
    assert colour_response.status_code == 302
    colour_location = colour_response.headers["Location"]
    colour_case_id = int(colour_location.rstrip("/").rsplit("/", 1)[-1])

    # 9) Reopen the case and complete it with the after-photo.
    reopened = c.get(f"/colour-lab/cases/{colour_case_id}")
    assert reopened.status_code == 200
    assert b"Critical Flow Colour Case" in reopened.data

    final_response = c.post(
        f"/colour-lab/cases/{colour_case_id}/complete",
        data={
            "_csrf_token": csrf,
            "result_rating": "Good match",
            "next_time_notes": "Repeat same formula next visit.",
            "result_notes": "Even tone and shine.",
            "after_photo": (jpeg_bytes(), "after.jpg"),
        },
        follow_redirects=False,
    )
    assert final_response.status_code == 302

    with salon.app.app_context():
        colour_case = salon.db.session.execute(
            salon.db.select(salon.ColourCase).where(
                salon.ColourCase.id == colour_case_id,
                salon.ColourCase.account_id == flow_account_id,
            )
        ).scalar_one_or_none()
        assert colour_case is not None
        assert colour_case.account_id == flow_account_id
        assert colour_case.customer_id == flow_customer_id
        assert colour_case.before_photo_data.startswith("data:image/jpeg;base64,")
        assert colour_case.after_photo_data.startswith("data:image/jpeg;base64,")

    # 10) Backup + recovery: export, mutate, restore, and verify exact recovery.
    backup = c.get("/backup/download")
    assert backup.status_code == 200
    assert backup.mimetype == "application/gzip"
    backup_bytes = backup.data

    with salon.app.app_context():
        flow_customer = salon.db.session.execute(
            salon.db.select(salon.Customer).where(
                salon.Customer.id == flow_customer_id,
                salon.Customer.account_id == flow_account_id,
            )
        ).scalar_one()
        assert flow_customer.notes == "Original recovery note"

    mutated = c.post(f"/customers/edit/{flow_customer_id}", data={
        "name": "Flow Customer",
        "phone": "9999998888",
        "email": "flow-customer@example.com",
        "gender": "Female",
        "notes": "MUTATED AFTER BACKUP",
    }, follow_redirects=True)
    assert mutated.status_code == 200

    with salon.app.app_context():
        mutated_customer = salon.db.session.execute(
            salon.db.select(salon.Customer).where(
                salon.Customer.id == flow_customer_id,
                salon.Customer.account_id == flow_account_id,
            )
        ).scalar_one()
        assert mutated_customer.notes == "MUTATED AFTER BACKUP"

    restored = c.post("/backup/restore", data={
        "restore_confirmation": "RESTORE",
        "backup_file": (BytesIO(backup_bytes), "salon-pro-backup.json.gz"),
    }, follow_redirects=True)
    assert restored.status_code == 200
    assert b"restore completed successfully" in restored.data.lower()

    with salon.app.app_context():
        recovered_customer = salon.db.session.execute(
            salon.db.select(salon.Customer).where(
                salon.Customer.id == flow_customer_id,
                salon.Customer.account_id == flow_account_id,
            )
        ).scalar_one_or_none()
        assert recovered_customer is not None
        assert recovered_customer.notes == "Original recovery note"
        recovered_case = salon.db.session.execute(
            salon.db.select(salon.ColourCase).where(
                salon.ColourCase.id == colour_case_id,
                salon.ColourCase.account_id == flow_account_id,
            )
        ).scalar_one_or_none()
        assert recovered_case is not None
        assert recovered_case.account_id == flow_account_id
        assert recovered_case.after_photo_data.startswith("data:image/jpeg;base64,")

    # 11) Logout and ensure the session is actually gone.
    logout = c.get("/logout", follow_redirects=False)
    assert logout.status_code == 302
    assert logout.headers["Location"].startswith("/login")
    with c.session_transaction() as sess:
        assert "user_id" not in sess
        assert "account_id" not in sess

    # The legacy tenant must still retain its original customer.
    with salon.app.app_context():
        assert salon.db.session.get(salon.AccountProfile, legacy_account_id) is not None
        legacy = salon.db.session.execute(
            salon.db.select(salon.Customer).where(
                salon.Customer.id == legacy_customer_id,
                salon.Customer.account_id == legacy_account_id,
            )
        ).scalar_one_or_none()
        assert legacy is not None
        assert legacy.account_id == legacy_account_id
