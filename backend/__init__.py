"""Shopify Sales Analysis dashboard: Flask backend + static frontend."""
from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .config import CORS_ORIGINS, DATA_FILE, FRONTEND_DIR, SHEET_NAME
from .data_loader import DataLoadError, load_sales_store  # noqa: F401  (re-exported)
from .routes import bp as api_blueprint

# The frontend loads only same-origin scripts/styles/fonts, so a strict policy is safe.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


def create_app(data_file: str | Path | None = None, sheet: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
    app.json.sort_keys = False
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # always serve the latest frontend files

    # Load (and validate) the data once at start-up. A bad file fails fast with a clear message.
    store = load_sales_store(Path(data_file) if data_file else DATA_FILE, SHEET_NAME if sheet is None else sheet)
    app.extensions["sales_store"] = store

    app.register_blueprint(api_blueprint)

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.after_request
    def add_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            origin = request.headers.get("Origin")
            if origin and origin in CORS_ORIGINS:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
        return response

    @app.errorhandler(404)
    def not_found(_err):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Unknown API endpoint."}), 404
        return "Not found", 404

    @app.errorhandler(405)
    def method_not_allowed(_err):
        return jsonify({"error": "Method not allowed. The API is read-only (GET)."}), 405

    @app.errorhandler(500)
    def server_error(_err):
        return jsonify({"error": "Unexpected server error. Check the terminal running the server."}), 500

    return app
