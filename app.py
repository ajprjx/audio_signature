"""Flask application factory for the audio signature API."""

from __future__ import annotations

import os

from flask import Flask, jsonify, send_from_directory

from api.routes import api_bp

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB uploads

    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.errorhandler(413)
    def too_large(_exc):
        return jsonify({"error": "Uploaded file too large."}), 413

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
