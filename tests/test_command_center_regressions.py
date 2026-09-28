import os
import sys
from datetime import date, timedelta

os.environ["DATABASE_URL"] = "sqlite:////tmp/salon_ci_command_center.db"
os.environ["SALON_PRO_SECRET_KEY"] = "test-command-center-secret"
os.environ["SALON_PRO_BILLING_REQUIRED"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as salon


def setup_database():
    salon.app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=os.environ["DATABASE_URL"],
        SALON_PRO_BILLING_REQUIRED=False,
    )
    with salon.app.app_context():
        salon.db.session.remove()
        salon.db.drop_all()
        salon.db.create_all()

        owner = salon.User(
            username="command-owner",
            password_hash=salon.generate_password_hash("password-123"),
            role="admin",
        )
        salon.db.session.add(owner)
        salon.db.session.flush()

        account = salon.AccountProfile(
            user_id=owner.id,
            business_name="Command Center Salon",
        )
        salon.db.session.add(account)
        salon.db.session.flush()

        salon.db.session.add(salon.SalonSetting(account_id=account.id))
        service = salon.Service(
            account_id=account.id,
            name="Signature Haircut",
            price=800,
            retention_min_days=30,
            retention_max_days=45,
        )
        staff = salon.Staff(
            account_id=account.id,
            name="Aman",
            is_active=True,
        )
        customer = salon.Customer(
            account_id=account.id,
            name="Anniversary Customer",
            phone="9000000123",
            date_of_birth=date.today(),
            anniversary_date=date.today(),
        )
        salon.db.session.add_all([service, staff, customer])
        salon.db.session.flush()

        salon.db.session.add(
            salon.Appointment(
                account_id=account.id,
                customer_id=customer.id,
                staff_id=staff.id,
                service_id=service.id,
                appointment_date=date.today() - timedelta(days=35),
                appointment_time="10:00",
                status="Completed",
            )
        )
        salon.db.session.commit()
        return owner.username, customer.id


def login(client):
    response = client.post(
        "/login",
        data={"username": "command-owner", "password": "password-123"},
        follow_redirects=True,
    )
    assert response.status_code == 200


def test_command_center_retention_shows_service_and_anniversary_action():
    setup_database()
    with salon.app.test_client() as client:
        login(client)
        response = client.get("/")
        assert response.status_code == 200
        assert b"Signature Haircut" in response.data
        assert b"/whatsapp/send/" in response.data
        assert b"/whatsapp/send/" in response.data and b"/anniversary" in response.data
        assert b"Anniversary" in response.data


def test_settings_invalid_business_hours_returns_validation_error_not_500():
    setup_database()
    data = {}
    for day in range(7):
        data[f"open_{day}"] = "20:00"
        data[f"close_{day}"] = "09:00"
    data["salon_name"] = "Command Center Salon"
    data["phone"] = ""
    data["address"] = ""
    data["tax_rate"] = "5"
    data["loyalty_rate"] = "1"
    data["loyalty_reward_threshold"] = "1000"
    data["loyalty_reward_value"] = "500"
    data["reminder_days"] = "1"
    data["invoice_prefix"] = "SP"
    data["gst_number"] = ""

    with salon.app.test_client() as client:
        login(client)
        response = client.post("/settings", data=data)
        assert response.status_code == 200
        assert b"closing time after opening time" in response.data

    with salon.app.app_context():
        assert salon.SalonHours.query.count() == 0
