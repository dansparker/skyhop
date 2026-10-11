"""E-mail sending via SMTP (stdlib). Without MAIL_SERVER, mails are kept in a dev outbox (see /dev/mails)."""
import logging
import smtplib
import ssl
import threading
from collections import deque
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from flask import current_app, render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

log = logging.getLogger("skyhop.mail")

# Newest first; holds mails when no SMTP server is configured (and always in tests)
outbox = deque(maxlen=50)


def absolute_url(path):
    """Turn a relative path into an absolute URL for use in e-mails."""
    if not path or path.startswith(("http://", "https://")):
        return path
    base = current_app.config.get("BASE_URL") or (request.host_url if request else "http://localhost:5000/")
    return base.rstrip("/") + "/" + path.lstrip("/")


def send_email(to, subject, template, action_url=None, action_label=None, **context):
    """Render email/<template>.txt and send it as text + HTML (wrapped in email/base.html)."""
    cfg = current_app.config
    action_url = absolute_url(action_url)
    context.update(action_url=action_url, action_label=action_label, base_url=absolute_url("/"))
    text = render_template(f"email/{template}.txt", **context).strip()
    html = render_template("email/base.html", subject=subject, paragraphs=_paragraphs(text), **context)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Skyhop", cfg["MAIL_DEFAULT_SENDER"]))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=cfg["MAIL_DEFAULT_SENDER"].split("@")[-1])
    if cfg.get("MAIL_REPLY_TO"):
        msg["Reply-To"] = cfg["MAIL_REPLY_TO"]
    if context.get("unsubscribe_url"):
        msg["List-Unsubscribe"] = f"<{context['unsubscribe_url']}>"
    msg.set_content(text + (f"\n\n{action_label or 'Link'}: {action_url}" if action_url else ""))
    msg.add_alternative(html, subtype="html")

    outbox.appendleft({"to": to, "subject": subject, "text": text, "action_url": action_url, "html": html})

    if cfg.get("TESTING") or not cfg.get("MAIL_SERVER"):
        log.info("E-Mail (nicht versendet, kein MAIL_SERVER) an %s: %s %s", to, subject, action_url or "")
        return msg

    smtp_cfg = {k: cfg.get(k) for k in
                ("MAIL_SERVER", "MAIL_PORT", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_USE_TLS", "MAIL_USE_SSL")}
    if cfg.get("MAIL_ASYNC", True):
        threading.Thread(target=_deliver, args=(smtp_cfg, msg), daemon=True).start()
    else:
        _deliver(smtp_cfg, msg)
    return msg


def _deliver(c, msg):
    try:
        if c["MAIL_USE_SSL"]:
            server = smtplib.SMTP_SSL(c["MAIL_SERVER"], c["MAIL_PORT"], context=ssl.create_default_context(), timeout=20)
        else:
            server = smtplib.SMTP(c["MAIL_SERVER"], c["MAIL_PORT"], timeout=20)
            if c["MAIL_USE_TLS"]:
                server.starttls(context=ssl.create_default_context())
        with server:
            if c["MAIL_USERNAME"]:
                server.login(c["MAIL_USERNAME"], c["MAIL_PASSWORD"] or "")
            server.send_message(msg)
        log.info("E-Mail an %s versendet: %s", msg["To"], msg["Subject"])
    except Exception:  # noqa: BLE001 – never break a request because of mail delivery
        log.exception("E-Mail an %s konnte nicht versendet werden", msg["To"])


def _paragraphs(text):
    return [p.strip() for p in text.split("\n\n") if p.strip()]


# --- Signed tokens (double opt-in, password reset, newsletter) ---------------------------------

def _serializer(purpose):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=f"skyhop-{purpose}")


def make_token(purpose, data):
    return _serializer(purpose).dumps(data)


def read_token(purpose, token, max_age):
    """Return the token payload, or None if invalid/expired."""
    try:
        return _serializer(purpose).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
