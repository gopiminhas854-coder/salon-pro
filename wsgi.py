import os
from app import app, init_db

# Gunicorn imports this module instead of running app.py as __main__.
# Initialize the production database before serving requests.
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
