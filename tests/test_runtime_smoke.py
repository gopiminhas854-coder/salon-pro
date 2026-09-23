import os
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/salon_ci_smoke.db"
os.environ["SALON_PRO_SECRET_KEY"] = "test-secret"
os.environ["SALON_PRO_AUTO_CREATE_DB"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app as salon


def setup_database():
    salon.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=os.environ["DATABASE_URL"])
    with salon.app.app_context():
        salon.db.session.remove()
        salon.db.drop_all()
        salon.db.create_all()
        salon.db.session.add(salon.User(
            username="admin",
            password_hash=salon.generate_password_hash("admin123"),
            role="admin",
        ))
        salon.db.session.add(salon.Customer(name="Smoke Customer", phone="9999999999"))
        salon.db.session.add(salon.Service(name="Smoke Service", duration_minutes=30, price=100, category="Hair", is_active=True))
        salon.db.session.add(salon.Staff(name="Smoke Staff", is_active=True))
        salon.db.session.commit()


def test_login_page_is_not_blank_and_static_css_loads():
    setup_database()
    with salon.app.test_client() as client:
        login_page = client.get("/login")
        assert login_page.status_code == 200
        assert b"Salon Pro" in login_page.data
        assert b'<form' in login_page.data
        css = client.get("/static/css/style.css")
        assert css.status_code == 200
        assert css.data.strip()


def test_dashboard_requires_login_then_renders_after_login():
    setup_database()
    with salon.app.test_client() as client:
        anonymous = client.get("/")
        assert anonymous.status_code == 302
        assert anonymous.headers["Location"].endswith("/login")

        response = client.post(
            "/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Overview" in response.data
        assert b"Today at a glance" in response.data


def test_health_reports_database_and_unknown_routes_are_not_blank():
    setup_database()
    with salon.app.test_client() as client:
        health = client.get("/health")
        assert health.status_code == 200
        payload = health.get_json()
        assert payload["status"] == "ok"
        assert payload["database"] == "ok"

        missing = client.get("/definitely-not-a-real-salon-pro-route")
        assert missing.status_code == 404
        assert b"Page not found" in missing.data
