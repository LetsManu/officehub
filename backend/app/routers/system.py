"""Administration → System: is everything running? Status of the stack, the meeting check and stack notices."""

from fastapi import APIRouter, Request

from ..deps import DB, Admin
from ..services import address, meetings, system

router = APIRouter(prefix="/api/admin/system", tags=["admin"])


@router.get("")
def overview(request: Request, user: Admin, db: DB) -> dict:
    data = system.overview(db)
    public = data["network"]["public"]["address"]
    seen = address.seen(request)
    # For the browser test of the relay: the same servers meetings get (their passwords last a few hours)
    data["ice_servers"] = meetings.ice_servers(f"system-{user.id}")
    # Seen from the server's own public address: the admin's browser is in the office network
    data["network"]["inside_office"] = (seen == public) if seen and public else None
    return data


@router.get("/notices")
def notices(user: Admin) -> dict:
    """Only what needs attention, for the hint at the top of the Administration page."""
    return {"notices": system.notices()}
