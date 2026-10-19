"""Small key/value store for portal-wide settings (JSON values in the settings table)."""

import json

from sqlalchemy.orm import Session

from ..models import Setting


def get_setting(db: Session, key: str, default):
    row = db.get(Setting, key)
    return json.loads(row.value) if row else default


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=json.dumps(value)))
    else:
        row.value = json.dumps(value)
