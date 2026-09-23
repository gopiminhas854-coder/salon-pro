import os

os.environ["DATABASE_URL"] = "sqlite:////tmp/salon_ci_wsgi.db"
os.environ["SALON_PRO_SECRET_KEY"] = "test-secret"
os.environ["SALON_PRO_AUTO_CREATE_DB"] = "1"


def test_wsgi_disables_html_caching():
    import wsgi

    wsgi.app.config.update(TESTING=True)
    with wsgi.app.app_context():
        wsgi.db.create_all() if hasattr(wsgi, "db") else None
    with wsgi.app.test_client() as client:
        response = client.get("/login")
        assert response.status_code == 200
        assert "no-store" in response.headers["Cache-Control"]
        assert response.headers["Pragma"] == "no-cache"
