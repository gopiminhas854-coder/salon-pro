import os
from flask import request
from app import app

# Database schema creation/migrations are handled by migrate_startup.py
# before Gunicorn starts. Do not call init_db() here: doing so can race with
# migrations on Render and can cause schema/transaction errors on startup.


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
