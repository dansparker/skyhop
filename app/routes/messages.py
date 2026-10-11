from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Conversation, Flight, Message, User
from ..utils import get_or_create_conversation, notify, parse_int

bp = Blueprint("messages", __name__, url_prefix="/nachrichten")


@bp.route("/")
@login_required
def inbox():
    convs = (
        Conversation.query.filter(
            db.or_(Conversation.user1_id == current_user.id, Conversation.user2_id == current_user.id)
        )
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    convs = [c for c in convs if c.messages]
    return render_template("messages/inbox.html", conversations=convs, active=None)


@bp.route("/<int:conv_id>", methods=["GET", "POST"])
@login_required
def thread(conv_id):
    conv = db.session.get(Conversation, conv_id) or abort(404)
    if not conv.has_member(current_user):
        abort(403)
    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if body:
            db.session.add(Message(conversation_id=conv.id, sender_id=current_user.id, body=body[:4000]))
            conv.updated_at = datetime.utcnow()
            other = conv.other(current_user)
            notify(other, f"Neue Nachricht von {current_user.short_name}", url_for("messages.thread", conv_id=conv.id))
            db.session.commit()
        return redirect(url_for("messages.thread", conv_id=conv.id) + "#bottom")
    changed = False
    for m in conv.messages:
        if m.sender_id != current_user.id and m.read_at is None:
            m.read_at = datetime.utcnow()
            changed = True
    if changed:
        db.session.commit()
    convs = (
        Conversation.query.filter(
            db.or_(Conversation.user1_id == current_user.id, Conversation.user2_id == current_user.id)
        )
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    convs = [c for c in convs if c.messages or c.id == conv.id]
    return render_template("messages/inbox.html", conversations=convs, active=conv)


@bp.route("/neu/<int:user_id>", methods=["GET", "POST"])
@login_required
def start(user_id):
    other = db.session.get(User, user_id) or abort(404)
    if other.id == current_user.id:
        flash("Du kannst dir nicht selbst schreiben.", "warning")
        return redirect(url_for("messages.inbox"))
    flight_id = parse_int(request.args.get("flight"))
    flight = db.session.get(Flight, flight_id) if flight_id else None
    conv = get_or_create_conversation(current_user, other, flight)
    db.session.commit()
    return redirect(url_for("messages.thread", conv_id=conv.id))
