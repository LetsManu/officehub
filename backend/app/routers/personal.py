"""Personal documents: files HR shares with exactly one person."""

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from ..deps import DB, Admin, CurrentUser
from ..errors import ApiError, not_found
from ..files import MIME_TYPES, delete_quietly, resolve, save_upload
from ..models import PersonalDocument, User, utcnow
from ..schemas import UserBrief, UtcDateTime
from ..services import notifications

router = APIRouter(prefix="/api/personal-documents", tags=["personal documents"])

PERSONAL_TYPES = {"pdf", "png", "jpg", "jpeg", "docx", "txt"}


class PersonalDocumentOut(BaseModel):
    id: int
    title: str
    file_name: str
    file_type: str
    file_size: int
    created_at: UtcDateTime
    opened_at: UtcDateTime | None
    person: UserBrief
    uploaded_by: UserBrief


def _out(doc: PersonalDocument, person: User) -> PersonalDocumentOut:
    return PersonalDocumentOut(
        id=doc.id,
        title=doc.title,
        file_name=doc.file_name,
        file_type=doc.file_type,
        file_size=doc.file_size,
        created_at=doc.created_at,
        opened_at=doc.opened_at,
        person=UserBrief.model_validate(person),
        uploaded_by=UserBrief.model_validate(doc.uploaded_by),
    )


def _load(db, document_id: int, user: User) -> PersonalDocument:
    doc = db.get(PersonalDocument, document_id)
    # Only the person and HR can see it; everyone else gets "not found".
    if doc is None or not (doc.user_id == user.id or user.is_admin):
        raise not_found("Document")
    return doc


@router.get("", response_model=list[PersonalDocumentOut])
def list_documents(user: CurrentUser, db: DB, person_id: int | None = None) -> list[PersonalDocumentOut]:
    """Your own documents; HR may pass person_id to see someone else's."""
    target_id = person_id if (person_id and user.is_admin) else user.id
    person = db.get(User, target_id)
    if person is None:
        raise not_found("Person")
    rows = db.scalars(
        select(PersonalDocument).where(PersonalDocument.user_id == target_id).order_by(PersonalDocument.created_at.desc())
    )
    return [_out(d, person) for d in rows]


@router.post("", response_model=PersonalDocumentOut, status_code=201)
async def upload(
    user: Admin, db: DB, file: UploadFile = File(...), person_id: int = Form(...), title: str = Form(...)
) -> PersonalDocumentOut:
    person = db.get(User, person_id)
    if person is None or not person.is_active:
        raise ApiError(422, "person_invalid", "Please choose active people.")
    title = title.strip()
    if not title or len(title) > 150:
        raise ApiError(422, "title_required", "Please enter a title (up to 150 characters).")
    stored = await save_upload(file, PERSONAL_TYPES, "personal")
    doc = PersonalDocument(
        user_id=person.id,
        title=title,
        file_name=stored.original_name,
        file_path=stored.relative_path,
        file_type=stored.file_type,
        file_size=stored.size,
        uploaded_by_id=user.id,
    )
    db.add(doc)
    db.flush()
    notifications.notify_many(db, [person.id], user, "personal_document", {"title": title}, "/documents?tab=mine")
    db.commit()
    db.refresh(doc)
    return _out(doc, person)


@router.get("/{document_id}/download")
def download(document_id: int, user: CurrentUser, db: DB) -> FileResponse:
    doc = _load(db, document_id, user)
    if doc.user_id == user.id and doc.opened_at is None:
        doc.opened_at = utcnow()
        db.commit()
    return FileResponse(
        resolve(doc.file_path),
        media_type=MIME_TYPES.get(doc.file_type, "application/octet-stream"),
        filename=doc.file_name,
        content_disposition_type="attachment",
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int, user: Admin, db: DB) -> None:
    doc = _load(db, document_id, user)
    path = doc.file_path
    db.delete(doc)
    db.commit()
    delete_quietly(path)
