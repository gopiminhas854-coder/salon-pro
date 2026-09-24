import os
import subprocess
import sys


def run_import(extra_env=None):
    env = os.environ.copy()
    env.update({
        "FLASK_ENV": "production",
        "DATABASE_URL": "sqlite:////tmp/salon_security_config.db",
        "SALON_PRO_SECRET_KEY": "a" * 64,
        "SALON_PRO_ADMIN_PASSWORD": "test-admin-password",
        "SALON_PRO_AUTO_CREATE_DB": "0",
    })
    env.update(extra_env or {})
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import app; "
                "print(app.app.config['SESSION_COOKIE_SECURE'])"
            ),
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def test_production_forces_secure_session_cookie():
    result = run_import({"SESSION_COOKIE_SECURE": "0"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_production_rejects_missing_secret_key():
    env = {
        "SALON_PRO_SECRET_KEY": "",
    }
    result = run_import(env)
    assert result.returncode != 0
    assert "SALON_PRO_SECRET_KEY" in result.stderr


def test_source_has_no_legacy_default_admin_password():
    with open("app.py", "r", encoding="utf-8") as handle:
        source = handle.read()
    assert "admin123" not in source
