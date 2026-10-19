"""Rules about people: reporting lines and onboarding checklists."""

from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import OnboardingTask, User

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
    if db.query(OnboardingTask).filter(OnboardingTask.user_id == person.id).first():
        return
    for order, (key, owner) in enumerate(DEFAULT_ONBOARDING):
        db.add(OnboardingTask(user_id=person.id, key=key, owner=owner, sort_order=order))
