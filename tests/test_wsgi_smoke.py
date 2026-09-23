import os

os.environ["DATABASE_URL"] = "sqlite:////tmp/salon_ci_wsgi.db"
os.environ["SALON_PRO_SECRET_KEY"] = "test-secret"
os.environ["SALON_PRO_ADMIN_PASSWORD"] = "test-admin-password"
os.environ["SALON_PRO_AUTO_CREATE_DB"] = "1"


def test_wsgi_disables_html_caching():
    from app import db
    import wsgi

    wsgi.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=os.environ["DATABASE_URL"])
    with wsgi.app.app_context():
        db.drop_all()
        db.create_all()
    with wsgi.app.test_client() as client:
        response = client.get("/login")
        assert response.status_code == 200
        assert "no-store" in response.headers["Cache-Control"]
        assert response.headers["Pragma"] == "no-cache"
