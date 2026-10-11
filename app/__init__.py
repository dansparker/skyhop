import os
import secrets
from datetime import datetime

from flask import Flask, abort, render_template, request, session
from flask_login import current_user

from .extensions import db, login_manager

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS = ["Jän", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def _env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    env = os.environ.get
    app.config.update(
        SECRET_KEY=env("SKYHOP_SECRET_KEY", "dev-only-change-me"),
        SQLALCHEMY_DATABASE_URI=env("DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "skyhop.db")),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SERVICE_FEE_RATE=0.10,
        CSRF_ENABLED=True,
        BASE_URL=env("BASE_URL", ""),
        TRUST_PROXY=_env_bool("TRUST_PROXY"),
        # E-mail (SMTP). Without MAIL_SERVER mails land in the dev inbox at /dev/mails.
        MAIL_SERVER=env("MAIL_SERVER", ""),
        MAIL_PORT=int(env("MAIL_PORT", "587")),
        MAIL_USERNAME=env("MAIL_USERNAME", ""),
        MAIL_PASSWORD=env("MAIL_PASSWORD", ""),
        MAIL_USE_TLS=_env_bool("MAIL_USE_TLS", True),
        MAIL_USE_SSL=_env_bool("MAIL_USE_SSL", False),
        MAIL_DEFAULT_SENDER=env("MAIL_DEFAULT_SENDER", "noreply@skyhop.local"),
        MAIL_REPLY_TO=env("MAIL_REPLY_TO", ""),
        # Payments (Stripe Checkout). Without STRIPE_SECRET_KEY bookings use demo payments.
        STRIPE_SECRET_KEY=env("STRIPE_SECRET_KEY", ""),
        STRIPE_WEBHOOK_SECRET=env("STRIPE_WEBHOOK_SECRET", ""),
        # Direct PayPal (REST API v2). PAYPAL_MODE: sandbox | live
        PAYPAL_CLIENT_ID=env("PAYPAL_CLIENT_ID", ""),
        PAYPAL_CLIENT_SECRET=env("PAYPAL_CLIENT_SECRET", ""),
        PAYPAL_MODE=env("PAYPAL_MODE", "sandbox"),
        PAYPAL_WEBHOOK_ID=env("PAYPAL_WEBHOOK_ID", ""),
        # Optional: which configured providers to offer and in which order, e.g. "paypal,stripe"
        PAYMENT_PROVIDERS=env("PAYMENT_PROVIDERS", "stripe,paypal"),
    )
    if config:
        app.config.update(config)
    if app.config["TRUST_PROXY"]:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .routes import admin, auth, bookings, flights, main, messages, newsletter, pilot, profile, wishes

    for bp in (main.bp, auth.bp, flights.bp, bookings.bp, messages.bp, pilot.bp, profile.bp, wishes.bp,
               newsletter.bp, admin.bp):
        app.register_blueprint(bp)

    _register_csrf(app)
    _register_template_helpers(app)
    _register_cli(app)

    with app.app_context():
        db.create_all()
        _add_missing_columns()
        from .airports import seed_airports

        seed_airports(db)

    return app


def _add_missing_columns():
    """Tiny auto-migration: add columns introduced after a database was created (SQLite dev databases)."""
    from sqlalchemy import inspect, text

    insp = inspect(db.engine)
    added = set()
    for table in db.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(db.engine.dialect)}'
            default = col.default.arg if col.default is not None and col.default.is_scalar else None
            if isinstance(default, bool):
                ddl += f" NOT NULL DEFAULT {int(default)}"
            elif isinstance(default, (int, float)):
                ddl += f" DEFAULT {default}"
            db.session.execute(text(ddl))
            added.add(f"{table.name}.{col.name}")
    if "user.email_confirmed" in added:
        # Accounts that existed before double opt-in was introduced count as confirmed
        db.session.execute(text('UPDATE "user" SET email_confirmed = 1'))
    if added:
        db.session.commit()


# Endpoints that receive POSTs from third parties and authenticate themselves (signature)
CSRF_EXEMPT = {"bookings.stripe_webhook", "bookings.paypal_webhook"}


def _register_csrf(app):
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_urlsafe(32)
        return session["_csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        if not app.config.get("CSRF_ENABLED") or request.endpoint in CSRF_EXEMPT:
            return
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not token or token != session.get("_csrf"):
                abort(400, description="Ungültiges oder abgelaufenes Formular. Bitte lade die Seite neu.")


def _register_template_helpers(app):
    from .models import Airport, Conversation, Message, Notification

    @app.template_filter("dt")
    def format_dt(value, fmt="full"):
        if not value:
            return ""
        if fmt == "date":
            return f"{WEEKDAYS[value.weekday()]}, {value.day}. {MONTHS[value.month - 1]} {value.year}"
        if fmt == "short":
            return f"{value.day}. {MONTHS[value.month - 1]}"
        if fmt == "time":
            return value.strftime("%H:%M")
        if fmt == "rel":
            delta = datetime.utcnow() - value
            s = int(delta.total_seconds())
            if s < 60:
                return "gerade eben"
            if s < 3600:
                return f"vor {s // 60} min"
            if s < 86400:
                return f"vor {s // 3600} h"
            return f"{value.day}. {MONTHS[value.month - 1]} {value.year}"
        return f"{WEEKDAYS[value.weekday()]}, {value.day}. {MONTHS[value.month - 1]} {value.year}, {value.strftime('%H:%M')}"

    @app.template_filter("eur")
    def format_eur(value):
        if value is None:
            return ""
        return f"{int(value):,} €".replace(",", ".")

    @app.template_filter("stars")
    def stars(value):
        if value is None:
            return ""
        full = int(round(value))
        return "★" * full + "☆" * (5 - full)

    # Global (not context-bound) so imported macros can use it too
    app.jinja_env.globals["airport_list"] = lambda: Airport.query.order_by(Airport.city).all()

    @app.context_processor
    def inject_globals():
        ctx = {"now": datetime.now()}
        if current_user.is_authenticated:
            ctx["unread_notifications"] = Notification.query.filter_by(user_id=current_user.id, read=False).count()
            ctx["unread_messages"] = (
                Message.query.join(Conversation)
                .filter(
                    db.or_(Conversation.user1_id == current_user.id, Conversation.user2_id == current_user.id),
                    Message.sender_id != current_user.id,
                    Message.read_at.is_(None),
                )
                .count()
            )
        return ctx

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("pages/error.html", code=403, message="Dafür hast du keine Berechtigung."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("pages/error.html", code=404, message="Diese Seite gibt es leider nicht."), 404

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("pages/error.html", code=400, message=e.description), 400


def _register_cli(app):
    @app.cli.command("seed")
    def seed_cmd():
        """Fill the database with demo users, aircraft, flights and reviews."""
        from .seed import seed_demo

        seed_demo()
        print("Demo-Daten angelegt.")

    @app.cli.command("reset-db")
    def reset_db_cmd():
        """Drop and recreate all tables."""
        from .airports import seed_airports

        db.drop_all()
        db.create_all()
        seed_airports(db)
        print("Datenbank zurückgesetzt.")
