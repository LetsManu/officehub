"""WordCraft and DeckCraft (https://github.com/storytold): open-source word processor and presentation program.

- In the browser: an optional container serves their web versions under /wordcraft/ and /deckcraft/. OfficeHub
  notices it by itself and opens a file there with a short-lived ticket; Save sends the file back as a new version.
- On the computer: the desktop programs open files of the portal through the network drive (WebDAV, /dav/).
"""

from sqlalchemy.orm import Session

from ..config import settings
from .probe import reachable
from .settings import get_setting

# What each program can edit and save back in the portal's file type
APPS = {
    "wordcraft": {"docx"},
    "deckcraft": {"pptx", "deckcraft"},
}


def available() -> list[str]:
    """The programs whose browser version is running in the stack."""
    if not settings.craft_internal_url:
        return []
    return [app for app in APPS if reachable(f"{settings.craft_internal_url}/{app}/index.html")]


def preferred(db: Session) -> bool:
    """Open Word and PowerPoint files in WordCraft / DeckCraft (instead of the office server)? Yes while they run,
    unless HR chose the office editor under Administration → Office editing."""
    return bool(available()) and get_setting(db, "office", {}).get("prefer_craft", True) is not False


def app_for(file_type: str) -> str | None:
    return next((app for app, types in APPS.items() if file_type in types), None)
