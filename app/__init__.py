from pathlib import Path

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from app.config import Config
from app.errors import ApiError
from app.extensions import db
from app.routes.health import health_bp
from app.routes.members import members_bp


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    app.json.sort_keys = False
    _ensure_sqlite_directory(app)

    db.init_app(app)

    app.register_blueprint(health_bp)
    app.register_blueprint(members_bp)

    _register_error_handlers(app)

    with app.app_context():
        db.create_all()

    return app


def _ensure_sqlite_directory(app):
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///") or ":memory:" in uri:
        return
    path = uri.removeprefix("sqlite:///")
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)


def _register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify({"message": error.message}), error.status_code

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return jsonify({"message": error.description}), error.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception("Unhandled error", exc_info=error)
        return jsonify({"message": "Internal server error"}), 500
