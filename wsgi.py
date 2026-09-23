import os
from app import app

# Database schema creation/migrations are handled by migrate_startup.py
# before Gunicorn starts. Do not call init_db() here: doing so can race with
# migrations on Render and can cause schema/transaction errors on startup.

@app.after_request
def prevent_stale_html_cache(response):
    # Dynamic pages must always reflect the current deployed UI. This avoids a
    # browser/PWA cache keeping an older HTML shell after a Render deployment.
    if request.path.endswith("/sw.js") or response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
