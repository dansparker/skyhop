import os
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, request, send_from_directory, url_for
from flask_login import current_user, login_required

from .. import uploads
from ..extensions import db
from ..models import Aircraft, PilotDocument
from ..utils import pilot_required

bp = Blueprint("uploads", __name__)


@bp.route("/media/<kind>/<filename>")
def media(kind, filename):
    """Public images (avatars, aircraft photos)."""
    if kind not in uploads.PUBLIC_KINDS or filename != os.path.basename(filename):
        abort(404)
    resp = send_from_directory(uploads.folder(kind), filename, max_age=60 * 60 * 24 * 30)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@bp.route("/dokumente/<int:doc_id>")
@login_required
def document(doc_id):
    """Private pilot documents – only for the owner and admins."""
    doc = db.session.get(PilotDocument, doc_id) or abort(404)
    if doc.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    resp = send_from_directory(uploads.folder(uploads.DOCUMENT_DIR), doc.filename, mimetype=doc.content_type,
                               as_attachment=False, download_name=f"{doc.kind}-{doc.user_id}-{doc.id}.{doc.filename.rsplit('.', 1)[-1]}",
                               max_age=0)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    return resp


@bp.route("/profil/foto", methods=["POST"])
@login_required
def avatar():
    if request.form.get("remove"):
        uploads.delete_file("avatars", current_user.avatar_filename)
        current_user.avatar_filename = None
        db.session.commit()
        flash("Profilfoto entfernt.", "info")
        return redirect(url_for("profile.edit"))
    try:
        name = uploads.save_image(request.files.get("photo"), "avatars", square=True)
    except uploads.UploadError as e:
        flash(str(e), "danger")
        return redirect(url_for("profile.edit"))
    uploads.delete_file("avatars", current_user.avatar_filename)
    current_user.avatar_filename = name
    db.session.commit()
    flash("Profilfoto gespeichert.", "success")
    return redirect(url_for("profile.edit"))


@bp.route("/pilot/flugzeuge/<int:aircraft_id>/foto", methods=["POST"])
@pilot_required
def aircraft_photo(aircraft_id):
    aircraft = db.session.get(Aircraft, aircraft_id) or abort(404)
    if aircraft.owner_id != current_user.id:
        abort(403)
    if request.form.get("remove"):
        uploads.delete_file("aircraft", aircraft.photo_filename)
        aircraft.photo_filename = None
        db.session.commit()
        flash("Foto entfernt.", "info")
    else:
        try:
            name = uploads.save_image(request.files.get("photo"), "aircraft")
        except uploads.UploadError as e:
            flash(str(e), "danger")
            return redirect(url_for("pilot.aircraft_edit", aircraft_id=aircraft.id))
        uploads.delete_file("aircraft", aircraft.photo_filename)
        aircraft.photo_filename = name
        db.session.commit()
        flash("Foto gespeichert.", "success")
    return redirect(url_for("pilot.aircraft_edit", aircraft_id=aircraft.id))


@bp.route("/pilot/dokumente", methods=["POST"])
@login_required
def upload_document():
    kind = request.form.get("kind")
    if kind not in PilotDocument.KINDS:
        abort(400)
    if current_user.pilot_status == "verified":
        flash("Du bist bereits verifiziert.", "info")
        return redirect(url_for("pilot.become"))
    if kind == "medical" and not request.form.get("health_consent"):
        flash("Für den Medical-Nachweis brauchen wir deine ausdrückliche Einwilligung (Gesundheitsdaten).", "danger")
        return redirect(url_for("pilot.become"))
    try:
        name, content_type, size = uploads.save_document(request.files.get("document"))
    except uploads.UploadError as e:
        flash(str(e), "danger")
        return redirect(url_for("pilot.become"))
    original = os.path.basename(request.files["document"].filename or "")[:200]
    db.session.add(PilotDocument(user_id=current_user.id, kind=kind, filename=name, original_name=original,
                                 content_type=content_type, size=size,
                                 consent_at=datetime.utcnow() if kind == "medical" else None))
    db.session.commit()
    flash(f"{PilotDocument.KINDS[kind]} hochgeladen.", "success")
    return redirect(url_for("pilot.become"))


@bp.route("/pilot/dokumente/<int:doc_id>/loeschen", methods=["POST"])
@login_required
def delete_document(doc_id):
    doc = db.session.get(PilotDocument, doc_id) or abort(404)
    if doc.user_id != current_user.id or doc.status == "approved":
        abort(403)
    uploads.delete_file(uploads.DOCUMENT_DIR, doc.filename)
    db.session.delete(doc)
    db.session.commit()
    flash("Dokument gelöscht.", "info")
    return redirect(url_for("pilot.become"))
