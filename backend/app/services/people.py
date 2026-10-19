"""Rules about people: reporting lines and onboarding checklists."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import Asset, OnboardingTask, User

# Default onboarding checklist. Keys are translated in the UI (onboarding.tasks.<key>).
DEFAULT_ONBOARDING = [
    ("hr_documents", "hr"),
    ("hr_handbook", "hr"),
    ("it_laptop", "it"),
    ("it_accounts", "it"),
    ("it_phone", "it"),
    ("manager_welcome", "manager"),
    ("manager_buddy", "manager"),
    ("manager_week", "manager"),
]

# Default offboarding checklist (onboarding.offTasks.<key>), plus one "return" task per item the person has.
DEFAULT_OFFBOARDING = [
    ("hr_exit_talk", "hr"),
    ("hr_reference", "hr"),
    ("hr_final_pay", "hr"),
    ("manager_handover", "manager"),
    ("manager_farewell", "manager"),
    ("it_data", "it"),
    ("it_accounts_off", "it"),
]


def check_manager(db: Session, person: User | None, manager_id: int | None) -> None:
    """A manager must be an active person and the reporting line must not loop."""
    if manager_id is None:
        return
    manager = db.get(User, manager_id)
    if manager is None or not manager.is_active:
        raise ApiError(422, "manager_invalid", "Please choose an active person as manager.")
    seen: set[int] = set()
    current: User | None = manager
    while current is not None:
        if person is not None and current.id == person.id:
            raise ApiError(422, "manager_cycle", "This would create a loop in the reporting line.")
        if current.id in seen:
            break
        seen.add(current.id)
        current = current.manager


def start_onboarding(db: Session, person: User) -> None:
    if db.query(OnboardingTask).filter(OnboardingTask.user_id == person.id, OnboardingTask.kind == "onboarding").first():
        return
    for order, (key, owner) in enumerate(DEFAULT_ONBOARDING):
        db.add(OnboardingTask(user_id=person.id, key=key, owner=owner, sort_order=order))


def start_offboarding(db: Session, person: User, last_day: date) -> None:
    person.last_day = last_day
    if db.query(OnboardingTask).filter(OnboardingTask.user_id == person.id, OnboardingTask.kind == "offboarding").first():
        return
    order = 0
    for order, (key, owner) in enumerate(DEFAULT_OFFBOARDING):
        db.add(OnboardingTask(user_id=person.id, key=key, owner=owner, kind="offboarding", sort_order=order))
    for asset in db.scalars(select(Asset).where(Asset.assigned_to_id == person.id).order_by(Asset.name)):
        order += 1
        db.add(OnboardingTask(
            user_id=person.id, key="asset_return", title=asset.name, owner="it", kind="offboarding",
            asset_id=asset.id, sort_order=order,
        ))
