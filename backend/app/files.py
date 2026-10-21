"""File storage on the local filesystem and text extraction for document search."""

import io
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from fastapi import UploadFile

from .config import settings
from .errors import ApiError

DOCUMENT_TYPES = {"pdf", "md", "txt", "docx"}
RECEIPT_TYPES = {"pdf", "png", "jpg", "jpeg"}
OFFICE_TYPES = {"docx", "xlsx", "pptx", "odt", "ods", "odp", "doc", "xls", "ppt", "rtf", "csv"}
SPACE_TYPES = OFFICE_TYPES | {"pdf", "md", "txt", "png", "jpg", "jpeg", "gif", "webp", "zip"}

MIME_TYPES = {
    "pdf": "application/pdf",
    "md": "text/plain; charset=utf-8",  # served as plain text so browsers never render it as HTML
    "txt": "text/plain; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    "ppt": "application/vnd.ms-powerpoint",
    "rtf": "application/rtf",
    "csv": "text/csv; charset=utf-8",
    "zip": "application/zip",
}

INLINE_TYPES = {"pdf", "png", "jpg", "jpeg", "gif", "webp", "md", "txt"}

_ZIP_TYPES = {"docx", "xlsx", "pptx", "odt", "ods", "odp", "zip"}
_OLE_TYPES = {"doc", "xls", "ppt"}  # old binary Office formats


@dataclass
class StoredFile:
    original_name: str
    relative_path: str
    file_type: str
    size: int
    data: bytes


def extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def safe_display_name(filename: str) -> str:
    name = Path(filename or "file").name
    name = re.sub(r"[^\w.\- ()]", "_", name).strip() or "file"
    return name[:200]


def matches_signature(file_type: str, data: bytes) -> bool:
    if file_type == "pdf":
        return data.startswith(b"%PDF")
    if file_type in _ZIP_TYPES:
        return data.startswith(b"PK")
    if file_type in _OLE_TYPES:
        return data.startswith(b"\xd0\xcf\x11\xe0")
    if file_type == "rtf":
        return data.startswith(b"{\\rtf")
    if file_type == "gif":
        return data.startswith(b"GIF8")
    if file_type == "webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if file_type == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if file_type in {"jpg", "jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if file_type in {"md", "txt", "csv"}:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return b"\x00" not in data
    return False


async def save_upload(upload: UploadFile, allowed: set[str], folder: str) -> StoredFile:
    file_type = extension(upload.filename or "")
    if file_type not in allowed:
        allowed_list = ", ".join(sorted(t.upper() for t in allowed))
        raise ApiError(422, "file_type", f"This file type is not supported. Allowed: {allowed_list}.")
    data = await upload.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise ApiError(422, "file_too_large", f"The file is larger than {settings.max_upload_mb} MB.")
    if not data:
        raise ApiError(422, "file_empty", "The file is empty.")
    if not matches_signature(file_type, data):
        raise ApiError(422, "file_invalid", "The file content does not match its file type.")

    relative = f"{folder}/{uuid.uuid4().hex}.{file_type}"
    target = settings.upload_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return StoredFile(safe_display_name(upload.filename or ""), relative, file_type, len(data), data)


def write_file(folder: str, file_type: str, data: bytes) -> str:
    relative = f"{folder}/{uuid.uuid4().hex}.{file_type}"
    target = settings.upload_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative


def resolve(relative_path: str) -> Path:
    """Return the absolute path of a stored file, refusing anything outside the upload folder."""
    path = (settings.upload_dir / relative_path).resolve()
    if settings.upload_dir not in path.parents or not path.is_file():
        raise ApiError(404, "file_missing", "The file could not be found.")
    return path


def delete_quietly(relative_path: str | None) -> None:
    if not relative_path:
        return
    try:
        resolve(relative_path).unlink()
    except Exception:  # noqa: BLE001 - a leftover file is not worth failing a request for
        pass


def extract_text(file_type: str, data: bytes) -> str:
    """Best-effort plain text for search. Returns an empty string if extraction fails."""
    try:
        if file_type in {"md", "txt", "csv"}:
            return data.decode("utf-8")
        if file_type == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages[:200])
        if file_type == "docx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(xml)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = ["".join(t.text or "" for t in p.iter(f"{ns}t")) for p in root.iter(f"{ns}p")]
            return "\n".join(p for p in paragraphs if p)
    except Exception:  # noqa: BLE001 - unreadable files are still stored, just not searchable
        return ""
    return ""
