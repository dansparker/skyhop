"""File uploads: public images (avatars, aircraft photos) and private pilot documents.

Images are decoded and re-encoded with Pillow: this proves they really are images, normalises orientation,
limits their size and strips all metadata (EXIF incl. GPS position). Documents (PDF/JPG/PNG) are checked by
their magic bytes and stored under a random name outside the static folder; only the owner and admins can
download them.
"""
import io
import os
import secrets

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

PUBLIC_KINDS = {"avatars": 512, "aircraft": 1600}  # kind → max edge in px
DOCUMENT_DIR = "documents"
DOCUMENT_TYPES = {  # magic bytes → (content type, extension)
    b"%PDF-": ("application/pdf", "pdf"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
}
Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard


class UploadError(ValueError):
    pass


def upload_root():
    root = current_app.config.get("UPLOAD_FOLDER") or os.path.join(current_app.instance_path, "uploads")
    os.makedirs(root, exist_ok=True)
    return root


def folder(kind):
    path = os.path.join(upload_root(), kind)
    os.makedirs(path, exist_ok=True)
    return path


def _read(file_storage):
    if not file_storage or not file_storage.filename:
        raise UploadError("Bitte wähle eine Datei aus.")
    data = file_storage.read(current_app.config["MAX_UPLOAD_BYTES"] + 1)
    if len(data) > current_app.config["MAX_UPLOAD_BYTES"]:
        raise UploadError(f"Die Datei ist zu groß (max. {current_app.config['MAX_UPLOAD_BYTES'] // 1_000_000} MB).")
    if not data:
        raise UploadError("Die Datei ist leer.")
    return data


def save_image(file_storage, kind, square=False):
    """Validate, resize and store a public image. Returns the new file name."""
    if kind not in PUBLIC_KINDS:
        raise ValueError(kind)
    data = _read(file_storage)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise UploadError("Das Bild konnte nicht gelesen werden. Erlaubt sind JPG, PNG und WebP.")
    if img.format not in ("JPEG", "PNG", "WEBP"):
        raise UploadError("Erlaubt sind JPG, PNG und WebP.")
    img = ImageOps.exif_transpose(img).convert("RGB")
    max_edge = PUBLIC_KINDS[kind]
    if square:
        img = ImageOps.fit(img, (max_edge, max_edge), method=Image.Resampling.LANCZOS)
    else:
        img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    name = f"{secrets.token_urlsafe(16)}.webp"
    img.save(os.path.join(folder(kind), name), "WEBP", quality=82, method=4)  # no metadata is written
    return name


def save_document(file_storage):
    """Validate and store a private document. Returns (file name, content type, size)."""
    data = _read(file_storage)
    for magic, (content_type, ext) in DOCUMENT_TYPES.items():
        if data.startswith(magic):
            break
    else:
        raise UploadError("Erlaubt sind PDF, JPG und PNG.")
    if content_type != "application/pdf":
        # Re-encode images as well (validates them and strips EXIF)
        try:
            img = Image.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img)
            img.thumbnail((3000, 3000))
            out = io.BytesIO()
            if content_type == "image/png":
                img.save(out, "PNG")
            else:
                img.convert("RGB").save(out, "JPEG", quality=90)
            data = out.getvalue()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise UploadError("Das Bild konnte nicht gelesen werden.")
    name = f"{secrets.token_urlsafe(24)}.{ext}"
    with open(os.path.join(folder(DOCUMENT_DIR), name), "wb") as fh:
        fh.write(data)
    return name, content_type, len(data)


def delete_file(kind, filename):
    if not filename:
        return
    path = os.path.join(upload_root(), kind, os.path.basename(filename))
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:  # e.g. file locked on Windows while being served – leave it, never fail the request
        current_app.logger.warning("Upload %s konnte nicht gelöscht werden", path)
