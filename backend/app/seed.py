"""Initial data: the first administrator, and fictional demo content when DEMO_MODE=true.

All demo people, email addresses (example.com is reserved for examples) and texts are invented.
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .files import write_file
from .models import (
    Announcement,
    Document,
    OnboardingTask,
    QuickLink,
    Request,
    RequestComment,
    RequestEvent,
    Review,
    Room,
    RoomBooking,
    Setting,
    User,
    Visitor,
)
from .services.people import start_onboarding
from .security import hash_password
from .workdays import count_working_days

logger = logging.getLogger("officehub.seed")

DEMO_PASSWORD = "demo1234"

DEMO_USERS = [
    # email, first, last, department, job title (de, en), role
    ("anna.mayer@example.com", "Anna", "Mayer", "Marketing", ("Marketing-Referentin", "Marketing Specialist"), "employee"),
    ("lukas.schmid@example.com", "Lukas", "Schmid", "Sales", ("Kundenbetreuer", "Account Manager"), "employee"),
    ("sara.novak@example.com", "Sara", "Novak", "Finance", ("Buchhalterin", "Accountant"), "employee"),
    ("tom.huber@example.com", "Tom", "Huber", "Operations", ("Teamleiter Office", "Office Team Lead"), "manager"),
    ("julia.weber@example.com", "Julia", "Weber", "HR", ("Personalleiterin", "HR Manager"), "admin"),
    ("max.gruber@example.com", "Max", "Gruber", "IT", ("IT-Administrator", "IT Administrator"), "employee"),
]

# Fictional numbers from the 555-01xx range reserved for examples
DEMO_PHONES = {
    "anna": ("+1 555 0101", "+1 555 0111", True),
    "lukas": ("+1 555 0102", "+1 555 0112", True),
    "sara": ("+1 555 0103", "", False),
    "tom": ("+1 555 0104", "+1 555 0114", True),
    "julia": ("+1 555 0105", "+1 555 0115", False),
    "max": ("+1 555 0106", "", False),
}

TEXT = {
    "de": {
        "office": "Hauptsitz, 2. Stock",
        "vacation_title": "Sommerurlaub",
        "vacation_reason": "Familienurlaub",
        "laptop_title": "Ubuntu-Laptop für Kundentermine",
        "laptop_item": "Ubuntu-Laptop, 14 Zoll",
        "laptop_desc": "Mein aktuelles Gerät ist fünf Jahre alt und für Präsentationen bei Kunden zu langsam.",
        "laptop_comment": "Ich kläre gerade mit der IT, welche Geräte verfügbar sind.",
        "expense_title": "Verpflegung Team-Meeting",
        "expense_desc": "Getränke und Snacks für das monatliche Team-Meeting.",
        "expense_decision": "Danke, wird mit der nächsten Gehaltsabrechnung erstattet.",
        "home_title": "Homeoffice am Freitag",
        "home_desc": "Ich möchte an diesem Tag von zu Hause arbeiten.",
        "home_decision": "An diesem Tag findet der Kunden-Workshop vor Ort statt. Bitte wähle einen anderen Tag.",
        "it_title": "Zugang zur Buchhaltungssoftware",
        "it_item": "Buchhaltungssoftware",
        "it_desc": "Für den Monatsabschluss benötige ich Bearbeitungsrechte.",
        "ann_welcome_title": "Willkommen im OfficeHub",
        "ann_welcome_body": "Ab sofort findest du hier alle Anträge, Dokumente und Neuigkeiten an einem Ort.\n\nBei Fragen hilft dir das HR-Team gerne weiter.",
        "ann_event_title": "Team-Meeting am Freitag",
        "ann_event_body": "Unser monatliches Team-Meeting findet im großen Besprechungsraum statt. Für Getränke und Snacks ist gesorgt.",
        "ann_it_title": "IT-Wartung am Samstag",
        "ann_it_body": "Am Samstag zwischen 8 und 12 Uhr sind E-Mail und Dateiablage kurzzeitig nicht erreichbar. Bitte speichere deine Arbeit vorher.",
        "rooms": [("Großer Besprechungsraum", 12, "Bildschirm, Videokonferenz, Whiteboard"), ("Kleiner Besprechungsraum", 4, "Bildschirm"), ("Fokusraum", 2, "")],
        "booking_team": "Team-Meeting",
        "booking_interview": "Bewerbungsgespräch",
        "booking_customer": "Kundentermin Vorbereitung",
        "visit_note": "Bitte Besucherausweis vorbereiten.",
        "appointment_title": "Termin mit HR",
        "appointment_desc": "Ich möchte über eine Weiterbildung sprechen.",
        "links": [("Wissensdatenbank", "https://wiki.example.com", "book", "Anleitungen und Antworten auf häufige Fragen"),
                  ("E-Learning", "https://learning.example.com", "graduation", "Online-Schulungen"),
                  ("Zeiterfassung", "https://time.example.com", "clock", "Arbeitszeiten erfassen"),
                  ("Servicedesk", "https://servicedesk.example.com", "lifebuoy", "IT-Probleme melden")],
        "prep_anna": {"achievements": "Neue Website-Kampagne erfolgreich gestartet.", "challenges": "Viele parallele Projekte im Herbst.", "support": "Eine Schulung zu Datenanalyse.", "wishes": "Mehr Verantwortung bei Social Media."},
        "goals_sara": "1. Monatsabschluss bis zum 5. Arbeitstag\n2. Schulung zur neuen Buchhaltungssoftware\n3. Vertretung im Einkauf übernehmen",
    },
    "en": {
        "office": "Head office, 2nd floor",
        "vacation_title": "Summer vacation",
        "vacation_reason": "Family holiday",
        "laptop_title": "Ubuntu laptop for customer meetings",
        "laptop_item": "Ubuntu laptop, 14 inch",
        "laptop_desc": "My current device is five years old and too slow for presentations at customer sites.",
        "laptop_comment": "I am checking with IT which devices are available.",
        "expense_title": "Team meeting catering",
        "expense_desc": "Drinks and snacks for the monthly team meeting.",
        "expense_decision": "Thank you, this will be reimbursed with the next payroll.",
        "home_title": "Home office on Friday",
        "home_desc": "I would like to work from home on this day.",
        "home_decision": "The on-site customer workshop takes place that day. Please choose another day.",
        "it_title": "Access to the accounting software",
        "it_item": "Accounting software",
        "it_desc": "I need edit rights for the month-end closing.",
        "ann_welcome_title": "Welcome to OfficeHub",
        "ann_welcome_body": "From now on you will find all requests, documents and news in one place.\n\nIf you have any questions, the HR team is happy to help.",
        "ann_event_title": "Team meeting on Friday",
        "ann_event_body": "Our monthly team meeting takes place in the large meeting room. Drinks and snacks will be provided.",
        "ann_it_title": "IT maintenance on Saturday",
        "ann_it_body": "On Saturday between 8 am and 12 noon, email and file storage will be briefly unavailable. Please save your work beforehand.",
        "rooms": [("Large meeting room", 12, "Screen, video conferencing, whiteboard"), ("Small meeting room", 4, "Screen"), ("Focus room", 2, "")],
        "booking_team": "Team meeting",
        "booking_interview": "Job interview",
        "booking_customer": "Customer meeting preparation",
        "visit_note": "Please prepare a visitor badge.",
        "appointment_title": "Appointment with HR",
        "appointment_desc": "I would like to talk about a training course.",
        "links": [("Knowledge base", "https://wiki.example.com", "book", "Guides and answers to common questions"),
                  ("E-learning", "https://learning.example.com", "graduation", "Online training courses"),
                  ("Time tracking", "https://time.example.com", "clock", "Record working hours"),
                  ("Service desk", "https://servicedesk.example.com", "lifebuoy", "Report IT problems")],
        "prep_anna": {"achievements": "Launched the new website campaign successfully.", "challenges": "Many parallel projects in autumn.", "support": "A training course on data analysis.", "wishes": "More responsibility for social media."},
        "goals_sara": "1. Month-end closing by the 5th working day\n2. Training for the new accounting software\n3. Act as deputy in purchasing",
    },
}

DOCUMENTS = {
    "de": [
        ("Mitarbeiterhandbuch", "handbook", "Alles Wichtige für deinen Arbeitsalltag.", "md", """# Mitarbeiterhandbuch

Willkommen! Dieses Handbuch fasst die wichtigsten Regeln für den Arbeitsalltag zusammen.

## Arbeitszeiten

- Kernarbeitszeit ist **Montag bis Freitag von 9 bis 15 Uhr**.
- Überstunden sprichst du bitte vorher mit deiner Führungskraft ab.

## Homeoffice

Homeoffice ist bis zu zwei Tage pro Woche möglich. Stelle dafür einen *Homeoffice-Antrag* im OfficeHub.

## Spesen

Belege reichst du innerhalb von 30 Tagen über einen *Spesenantrag* ein.

## Ansprechpersonen

- Personalfragen: HR-Team
- Technik: IT-Service
"""),
        ("Urlaubsrichtlinie", "policy", "So beantragst du Urlaub und wie viele Tage dir zustehen.", "md", """# Urlaubsrichtlinie

## Urlaubsanspruch

Vollzeitbeschäftigte haben **25 Urlaubstage** pro Kalenderjahr.

## Urlaub beantragen

1. Öffne im OfficeHub **Urlaub beantragen**.
2. Wähle Start- und Enddatum. Die Arbeitstage werden automatisch berechnet.
3. Prüfe deine Angaben und sende den Antrag ab.

Bitte beantrage längeren Urlaub (mehr als 5 Tage) mindestens **vier Wochen** im Voraus.

## Übertrag

Resturlaub kann bis zum 31. März des Folgejahres genommen werden.
"""),
        ("IT-Richtlinien", "it", "Regeln für Passwörter, Geräte und Datenschutz.", "txt", """IT-Richtlinien

1. Passwörter
Verwende für jedes System ein eigenes Passwort mit mindestens 12 Zeichen. Gib Passwörter niemals weiter.

2. Geräte
Sperre deinen Bildschirm, wenn du den Arbeitsplatz verlässt. Neue Geräte beantragst du über einen Geräteantrag.

3. E-Mail
Öffne keine unerwarteten Anhänge. Melde verdächtige E-Mails an den IT-Service.

4. Zugänge
Zugriff auf neue Systeme beantragst du über einen IT-Zugangsantrag im OfficeHub.
"""),
    ],
    "en": [
        ("Employee handbook", "handbook", "Everything important for your working day.", "md", """# Employee handbook

Welcome! This handbook summarises the most important rules for everyday work.

## Working hours

- Core hours are **Monday to Friday, 9 am to 3 pm**.
- Please agree on overtime with your manager in advance.

## Home office

You can work from home up to two days per week. Submit a *home-office request* in OfficeHub.

## Expenses

Submit receipts within 30 days using an *expense request*.

## Contacts

- People questions: HR team
- Technology: IT service
"""),
        ("Vacation policy", "policy", "How to request vacation and how many days you have.", "md", """# Vacation policy

## Vacation entitlement

Full-time employees have **25 vacation days** per calendar year.

## Requesting vacation

1. Open **Request vacation** in OfficeHub.
2. Choose the start and end date. Working days are calculated automatically.
3. Check your details and send the request.

Please request longer vacations (more than 5 days) at least **four weeks** in advance.

## Carry-over

Remaining days can be taken until 31 March of the following year.
"""),
        ("IT guidelines", "it", "Rules for passwords, devices and data protection.", "txt", """IT guidelines

1. Passwords
Use a separate password with at least 12 characters for every system. Never share passwords.

2. Devices
Lock your screen when you leave your desk. Request new devices with an equipment request.

3. Email
Do not open unexpected attachments. Report suspicious emails to the IT service.

4. Access
Request access to new systems with an IT access request in OfficeHub.
"""),
    ],
}


def demo_accounts() -> list[dict]:
    return [
        {"email": email, "name": f"{first} {last}", "department": dept, "role": role}
        for email, first, last, dept, _titles, role in DEMO_USERS
    ]


def ensure_initial_data(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)) is not None:
        return
    if settings.demo_mode:
        seed_demo(db)
        logger.warning("Demo mode: fictional demo data created. Password for all demo accounts: %s", DEMO_PASSWORD)
        return
    if settings.admin_email and settings.admin_password:
        db.add(
            User(
                email=settings.admin_email.strip().lower(),
                password_hash=hash_password(settings.admin_password),
                first_name="OfficeHub",
                last_name="Admin",
                role="admin",
                language="de",
            )
        )
        db.commit()
        logger.warning("Created the first administrator account %s. Please change its password.", settings.admin_email)
    else:
        logger.warning("No users exist. Set ADMIN_EMAIL and ADMIN_PASSWORD (or DEMO_MODE=true) and restart.")


def _next_weekday(start: date, weekday: int) -> date:
    return start + timedelta(days=(weekday - start.weekday()) % 7 or 7)


def _at(day_offset: int, hour: int = 9) -> datetime:
    base = datetime.now(timezone.utc).replace(tzinfo=None, hour=hour, minute=0, second=0, microsecond=0)
    return base + timedelta(days=day_offset)


def seed_demo(db: Session) -> None:
    lang = settings.demo_language
    t = TEXT[lang]
    today = date.today()

    users: dict[str, User] = {}
    for email, first, last, dept, titles, role in DEMO_USERS:
        user = User(
            email=email,
            password_hash=hash_password(DEMO_PASSWORD),
            first_name=first,
            last_name=last,
            department=dept,
            job_title=titles[0 if lang == "de" else 1],
            office_location=t["office"],
            language=lang,
            role=role,
        )
        db.add(user)
        users[first.lower()] = user
    db.flush()
    anna, lukas, sara, tom, julia, max_ = (users[n] for n in ("anna", "lukas", "sara", "tom", "julia", "max"))
    for key, (phone, mobile, show_mobile) in DEMO_PHONES.items():
        users[key].phone, users[key].mobile, users[key].show_mobile = phone, mobile, show_mobile
    for person in (anna, lukas, sara, max_):
        person.manager_id = tom.id
    tom.manager_id = julia.id

    def add_request(requester: User, status: str, created_days_ago: int, **fields) -> Request:
        created = _at(-created_days_ago)
        req = Request(requester_id=requester.id, status=status, created_at=created, updated_at=created, **fields)
        if req.start_date and req.end_date:
            req.working_days = count_working_days(req.start_date, req.end_date)
        db.add(req)
        db.add(RequestEvent(request=req, actor_id=requester.id, action="created", created_at=created))
        if status != "draft":
            req.submitted_at = created
            db.add(RequestEvent(request=req, actor_id=requester.id, action="submitted", created_at=created))
        return req

    vacation_start = _next_weekday(today + timedelta(days=21), 0)
    add_request(
        anna, "submitted", 1, type="vacation", title=t["vacation_title"], description=t["vacation_reason"],
        start_date=vacation_start, end_date=vacation_start + timedelta(days=4),
    )

    laptop = add_request(
        lukas, "in_review", 4, type="equipment", title=t["laptop_title"], description=t["laptop_desc"],
        category="laptop", item=t["laptop_item"], needed_by=today + timedelta(days=14),
    )
    db.add(RequestEvent(request=laptop, actor_id=tom.id, action="in_review", created_at=_at(-3)))
    db.add(RequestComment(request=laptop, author_id=tom.id, body=t["laptop_comment"], created_at=_at(-3, 10)))
    laptop.updated_at = _at(-3, 10)

    expense = add_request(
        sara, "approved", 9, type="expense", title=t["expense_title"], description=t["expense_desc"],
        start_date=today - timedelta(days=10), amount_cents=int(Decimal("86.40") * 100), currency="EUR", category="meals",
    )
    expense.decided_by_id, expense.decided_at, expense.decision_comment = tom.id, _at(-8), t["expense_decision"]
    expense.updated_at = expense.decided_at
    db.add(RequestEvent(request=expense, actor_id=tom.id, action="approved", created_at=_at(-8)))

    friday = _next_weekday(today, 4)
    home = add_request(
        lukas, "rejected", 3, type="home_office", title=t["home_title"], description=t["home_desc"],
        start_date=friday, end_date=friday,
    )
    home.decided_by_id, home.decided_at, home.decision_comment = tom.id, _at(-2), t["home_decision"]
    home.updated_at = home.decided_at
    db.add(RequestEvent(request=home, actor_id=tom.id, action="rejected", created_at=_at(-2)))

    add_request(
        sara, "draft", 0, type="it_access", title=t["it_title"], description=t["it_desc"],
        item=t["it_item"], access_level="edit",
    )

    db.add_all([
        Announcement(
            title=t["ann_welcome_title"], body=t["ann_welcome_body"], category="general",
            publish_date=today - timedelta(days=7), pinned=True, author_id=julia.id,
        ),
        Announcement(
            title=t["ann_event_title"], body=t["ann_event_body"], category="event",
            publish_date=today - timedelta(days=2), event_date=friday, author_id=julia.id,
        ),
        Announcement(
            title=t["ann_it_title"], body=t["ann_it_body"], category="it",
            publish_date=today - timedelta(days=1), expiry_date=_next_weekday(today, 5) + timedelta(days=1),
            author_id=julia.id,
        ),
    ])

    for title, category, description, file_type, content in DOCUMENTS[lang]:
        data = content.encode("utf-8")
        db.add(
            Document(
                title=title, category=category, description=description,
                file_name=f"{title.lower().replace(' ', '-')}.{file_type}",
                file_path=write_file("documents", file_type, data), file_type=file_type,
                file_size=len(data), content_text=content, uploaded_by_id=julia.id,
                created_at=_at(-30), updated_at=_at(-5),
            )
        )

    _seed_workplace(db, t, today, anna, lukas, sara, tom, julia, max_)
    db.commit()


def _seed_workplace(db: Session, t: dict, today: date, anna, lukas, sara, tom, julia, max_) -> None:
    """Rooms, visitors, reviews, onboarding, quick links and portal settings for the demo."""
    rooms = [Room(name=name, seats=seats, equipment=equipment) for name, seats, equipment in t["rooms"]]
    db.add_all(rooms)
    db.flush()
    tomorrow = today + timedelta(days=1)
    db.add_all([
        RoomBooking(room_id=rooms[0].id, user_id=tom.id, title=t["booking_team"], day=today, start_time="09:00", end_time="10:00"),
        RoomBooking(room_id=rooms[1].id, user_id=julia.id, title=t["booking_interview"], day=today, start_time="14:00", end_time="15:00"),
        RoomBooking(room_id=rooms[1].id, user_id=anna.id, title=t["booking_customer"], day=tomorrow, start_time="10:00", end_time="11:00"),
    ])

    db.add_all([
        Visitor(name="Martin Keller", company="Beispiel GmbH", visit_date=today, expected_time="10:30",
                note=t["visit_note"], host_id=tom.id, created_by_id=tom.id),
        Visitor(name="Eva Lang", company="Muster AG", visit_date=today, expected_time="14:00",
                host_id=julia.id, created_by_id=julia.id),
    ])

    next_week = today + timedelta(days=7 - today.weekday() + 1)  # Tuesday next week
    appointment = Request(
        requester_id=lukas.id, type="appointment", status="submitted", title=t["appointment_title"],
        description=t["appointment_desc"], category="hr", submitted_at=_at(0),
        proposed_times=json.dumps([f"{next_week}T09:00", f"{next_week}T14:00", f"{next_week + timedelta(days=1)}T10:30"]),
        created_at=_at(0), updated_at=_at(0),
    )
    db.add(appointment)
    db.add(RequestEvent(request=appointment, actor_id=lukas.id, action="created", created_at=_at(0)))
    db.add(RequestEvent(request=appointment, actor_id=lukas.id, action="submitted", created_at=_at(0)))

    db.add(Review(employee_id=anna.id, reviewer_id=tom.id, year=today.year, meeting_date=today + timedelta(days=10),
                  employee_prep=json.dumps(t["prep_anna"]), employee_prep_done=True))
    db.add(Review(employee_id=sara.id, reviewer_id=tom.id, year=today.year - 1, status="completed",
                  meeting_date=today - timedelta(days=200), goals=t["goals_sara"],
                  employee_prep_done=True, reviewer_prep_done=True,
                  employee_confirmed_at=_at(-199), reviewer_confirmed_at=_at(-199)))

    start_onboarding(db, max_)
    db.flush()
    for task in db.query(OnboardingTask).filter(OnboardingTask.user_id == max_.id, OnboardingTask.key.in_(["hr_documents", "it_laptop", "it_accounts"])):
        task.done_at, task.done_by_id = _at(-1), julia.id

    for order, (title, url, icon, description) in enumerate(t["links"]):
        db.add(QuickLink(title=title, url=url, icon=icon, description=description, sort_order=order))

    db.add(Setting(key="dashboard_tiles", value=json.dumps(["vacation", "expense", "equipment", "rooms", "directory", "documents"])))
    db.add(Setting(key="section_contacts", value=json.dumps({
        "dashboard": julia.id, "requests": julia.id, "documents": julia.id, "announcements": julia.id,
        "directory": julia.id, "rooms": tom.id, "visitors": tom.id,
    })))

