"""Desktop sync (the Windows app's "OfficeHub" folder in Explorer, like OneDrive).

Every change to a space, folder or file gets the next number from one counter (sync_state), set by a hook on the
database session, so no way of changing files is missed: the portal, the network drive, the office servers, the
craft programs and the sync itself. Things removed for good leave a tombstone. A sync client asks "what changed
after number N" (routers/sync.py) and gets the items with a higher number; the trash counts as deleted.
"""

from datetime import timedelta

from sqlalchemy import event, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import Folder, Space, SpaceFile, SyncState, SyncTombstone, utcnow

TRACKED = (Space, Folder, SpaceFile)
TOMBSTONE_DAYS = 90


def _next_seq(session: Session) -> int:
    # Plain statements: the session is about to flush and cannot flush objects of its own here
    session.execute(sqlite_insert(SyncState).values(id=1, seq=0).on_conflict_do_nothing())
    session.execute(update(SyncState).where(SyncState.id == 1).values(seq=SyncState.seq + 1))
    return session.scalar(select(SyncState.seq).where(SyncState.id == 1)) or 0


@event.listens_for(Session, "before_flush")
def _number_changes(session: Session, _context, _instances) -> None:
    changed = [o for o in session.new if isinstance(o, TRACKED)]
    changed += [o for o in session.dirty if isinstance(o, TRACKED) and session.is_modified(o, include_collections=False)]
    removed = [o for o in session.deleted if isinstance(o, TRACKED)]
    if not changed and not removed:
        return
    seq = _next_seq(session)
    for item in changed:
        item.sync_seq = seq
    for item in removed:
        kind = "space" if isinstance(item, Space) else "folder" if isinstance(item, Folder) else "file"
        space_id = item.id if isinstance(item, Space) else item.space_id
        session.add(SyncTombstone(seq=seq, kind=kind, item_id=item.id, space_id=space_id))


def current(db: Session) -> int:
    return db.scalar(select(SyncState.seq).where(SyncState.id == 1)) or 0


def oldest_kept(db: Session) -> int:
    """Clients that last synced before this number start over (their tombstones are gone)."""
    return db.scalar(select(func.min(SyncTombstone.seq))) or 0


def prune(db: Session) -> None:
    db.query(SyncTombstone).filter(SyncTombstone.created_at < utcnow() - timedelta(days=TOMBSTONE_DAYS)).delete()
