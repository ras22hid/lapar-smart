import os
import secrets
import warnings
from flask import Flask
from dotenv import load_dotenv

from .db import init_db

load_dotenv()


def create_app():
    app = Flask(__name__)

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        # No hardcoded fallback: generate a random key so a missing env var
        # never means "use a fixed, publicly-known secret" -- but on a
        # platform with multiple concurrent instances (Vercel), each one
        # would then mint its *own* random key, so a session cookie signed
        # by one instance would fail validation on another. Warn loudly
        # rather than fail silently; production must set SECRET_KEY.
        secret_key = secrets.token_hex(32)
        if os.environ.get("VERCEL"):
            warnings.warn(
                "SECRET_KEY is not set: a random per-instance key was "
                "generated, which will make sessions invalid whenever a "
                "different warm instance handles a later request. Set "
                "SECRET_KEY in the Vercel project's environment variables.",
                RuntimeWarning,
            )
    app.secret_key = secret_key

    with app.app_context():
        init_db()

    from .routes_staff import staff_bp
    from .routes_admin import admin_bp

    app.register_blueprint(staff_bp)
    app.register_blueprint(admin_bp)

    return app
