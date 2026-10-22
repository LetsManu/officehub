import re

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select

from ..deps import DB, HR, CurrentUser
from ..errors import ApiError, not_found
from ..files import DOCUMENT_TYPES, MIME_TYPES, delete_quietly, extract_text, resolve, save_upload
from ..models import Document, User, utcnow
from ..schemas import DOCUMENT_CATEGORIES, DocumentContent, DocumentOut, DocumentUpdate
from ..services.audit import audit

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _get(db, document_id: int, user: User) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or (doc.archived and not user.is_hr):
        raise not_found("Document")
    return doc


def _snippet(text: str, term: str, radius: int = 80) -> str | None:
    match = re.search(re.escape(term), text, re.IGNORECASE)
    if not match:
        return None
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    # Drop Markdown markers so the preview reads like plain text.
    snippet = " ".join(re.sub(r"[#*_`>]+", "", text[start:end]).split())
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_meta(title: str, category: str, description: str) -> tuple[str, str, str]:
    title = title.strip()
    if not title or len(title) > 150:
        raise ApiError(422, "title_required", "Please enter a title (up to 150 characters).")
    if category not in DOCUMENT_CATEGORIES:
        raise ApiError(422, "category_required", "Please select a category.")
    description = description.strip()
    if len(description) > 1000:
        raise ApiError(422, "description_too_long", "The description can be at most 1000 characters.")
    return title, category, description


@router.get("", response_model=list[DocumentOut])
def list_documents(
    user: CurrentUser,
    db: DB,
    q: str | None = Query(None, max_length=100),
    category: str | None = None,
    include_archived: bool = False,
    sort: str = "title",
) -> list[DocumentOut]:
    if sort not in ("title", "updated"):
        raise ApiError(422, "invalid_sort", "Sort by 'title' or 'updated'.")
    query = select(Document)
    if not (include_archived and user.is_hr):
        query = query.where(Document.archived.is_(False))
    if category:
        query = query.where(Document.category == category)
    term = (q or "").strip()
    if term:
        pattern = f"%{_escape_like(term)}%"
        query = query.where(
            or_(
                Document.title.ilike(pattern, escape="\\"),
                Document.description.ilike(pattern, escape="\\"),
                Document.content_text.ilike(pattern, escape="\\"),
            )
        )
    order = (Document.updated_at.desc(), Document.title) if sort == "updated" else (Document.title,)
    docs = db.scalars(query.order_by(*order)).all()
    result = []
    for doc in docs:
        out = DocumentOut.model_validate(doc)
        if term and term.lower() not in doc.title.lower():
            out.snippet = _snippet(doc.content_text, term) or _snippet(doc.description, term)
        result.append(out)
    return result


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    user: HR,
    db: DB,
    file: UploadFile = File(...),
    title: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
) -> Document:
    title, category, description = _validate_meta(title, category, description)
    stored = await save_upload(file, DOCUMENT_TYPES, "documents")
    doc = Document(
        title=title,
        category=category,
        description=description,
        file_name=stored.original_name,
        file_path=stored.relative_path,
        file_type=stored.file_type,
        file_size=stored.size,
        content_text=extract_text(stored.file_type, stored.data),
        uploaded_by_id=user.id,
    )
    db.add(doc)
    audit(db, user, "document_uploaded", title)
    db.commit()
    return doc


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, user: CurrentUser, db: DB) -> Document:
    return _get(db, document_id, user)


@router.patch("/{document_id}", response_model=DocumentOut)
def update_document(document_id: int, body: DocumentUpdate, user: HR, db: DB) -> Document:
    doc = _get(db, document_id, user)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(doc, field, value)
    audit(db, user, "document_updated", doc.title, **{k: str(v) for k, v in changes.items()})
    db.commit()
    return doc


@router.post("/{document_id}/file", response_model=DocumentOut)
async def replace_file(document_id: int, user: HR, db: DB, file: UploadFile = File(...)) -> Document:
    doc = _get(db, document_id, user)
    stored = await save_upload(file, DOCUMENT_TYPES, "documents")
    old_path = doc.file_path
    doc.file_name = stored.original_name
    doc.file_path = stored.relative_path
    doc.file_type = stored.file_type
    doc.file_size = stored.size
    doc.content_text = extract_text(stored.file_type, stored.data)
    doc.updated_at = utcnow()
    audit(db, user, "document_replaced", doc.title, file=stored.original_name)
    db.commit()
    delete_quietly(old_path)
    return doc


@router.get("/{document_id}/content", response_model=DocumentContent)
def document_content(document_id: int, user: CurrentUser, db: DB) -> DocumentContent:
    doc = _get(db, document_id, user)
    if doc.file_type not in {"md", "txt"}:
        raise ApiError(415, "no_preview", "This document can only be downloaded.")
    return DocumentContent(format=doc.file_type, text=resolve(doc.file_path).read_text("utf-8"))


@router.get("/{document_id}/download")
def download_document(document_id: int, user: CurrentUser, db: DB, inline: bool = False) -> FileResponse:
    doc = _get(db, document_id, user)
    return FileResponse(
        resolve(doc.file_path),
        media_type=MIME_TYPES.get(doc.file_type, "application/octet-stream"),
        filename=doc.file_name,
        content_disposition_type="inline" if inline and doc.file_type == "pdf" else "attachment",
    )
