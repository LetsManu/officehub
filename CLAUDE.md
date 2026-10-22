# OfficeHub – notes for Claude Code

OfficeHub is a self-hosted employee portal (requests, documents, announcements).
It must stay simple for non-technical office employees. **Never add AI features,
chatbots, external APIs or cloud dependencies to the application.** Office editing uses the
company's own Collabora/ONLYOFFICE containers in the same stack, never a cloud service. Meetings and calls are built
in (WebRTC between browsers, signalling via `/api/rtc`, no outside STUN) and use the company's own Jitsi containers
when they run (OfficeHub's own UI via lib-jitsi-meet, never meet.jit.si). Nothing may need manual setup: optional
servers are detected (`services/probe.py`) and shared passwords are generated (`config._shared_secret`).
Presence (`services/presence.py`) and meeting reminders come with the `/api/me/summary` heartbeat (every 30 s);
desktop notifications use the browser's Notification API only (no outside push service). Series: `services/recurrence.py`.

## Layout

- `backend/` – FastAPI + SQLAlchemy + SQLite. Entry point `app/main.py`.
  - `app/routers/` – one module per API area; permission checks live here.
  - `app/services/requests.py` – request validation per type, permissions, serialization.
  - `app/services/people.py` – reporting lines and default onboarding checklist.
  - `app/db.py` – `add_missing_columns()` upgrades existing databases; new columns need a default
    (`server_default`) or must be nullable.
  - `app/seed.py` – first admin and fictional demo data (`DEMO_MODE=true`).
  - `app/routers/spaces.py`, `boards.py`, `chat.py`, `wiki.py`, `office.py` – team spaces. `/wopi/*` and
    `/office-hooks/*` are only for the office servers inside the Docker network (not proxied by nginx).
  - `app/routers/meetings.py`, `app/services/meetings.py`, `app/routers/rtc.py` – meetings, calls, guests; built-in
    signalling or Jitsi JWTs. Keep these endpoints app-friendly (future Windows/Android apps use them).
    Moderation (`mod` in the room token: organizer, or everyone in space rooms/calls), reactions and whiteboard go as
    small "app" messages; breakout rooms (`services/breakouts.py`, `/api/rtc/breakouts`) work with either token kind.
  - `app/routers/sso.py`, `app/services/sso.py` – company login with the company's own OpenID Connect server
    (Authentik, Keycloak); set up in Administration, password sign-in always stays.
  - `app/routers/webdav.py` – spaces as a network drive (`/dav/`, Basic auth with app passwords only,
    `services/app_passwords.py`). `app/routers/craft.py` + `craft/` – WordCraft/DeckCraft web builds (optional
    container, detected like the office servers) open `?src=` and PUT Save to `?save=` with a file ticket. Check-out
    (`ensure_can_change` in `services/spaces.py`) applies to every way of saving. Built from the forks
    LetsManu/wordcraft + LetsManu/deckcraft (branch `officehub`). Both edit together live: `services/collab.py`
    relays Yjs updates per file (`/api/craft/collab/<file>`, long polling like `/api/rtc`), one shared lock
    `craft:0:<token>`; automatic saves (`?auto=1`) go into one "together" version.
  - `tests/` – pytest, uses demo data; run `python -m pytest -q` in `backend/`.
- `frontend/` – Vue 3 + Vite + TypeScript, no UI library.
  - `src/locales/de.ts` is the source of truth for UI text; `en.ts` must have the same keys.
  - `src/components/` – shared building blocks (BaseModal, FormField, EmptyState, StatusBadge …).
  - `src/styles.css` – design tokens. Follow `docs/ui-guidelines.md`.
  - `src/lib/changelog.ts` – plain-language "What's new" entries; add one per release.
  - No inline `style="…"` attributes: the Content-Security-Policy blocks them. Use classes.
  - Run `npm test` (translations + logic) and `npm run build` (includes type check).

## Conventions

- Every UI string goes through `t('…')` in **both** `de.ts` and `en.ts`. Use plain, friendly
  language without technical terms (see `docs/ui-guidelines.md` → Writing).
- Show user content with `{{ }}` interpolation only. `v-html` is allowed only with
  `renderMarkdown()` / `renderChat()` from `src/lib/markdown.ts`, which escape HTML first.
- API errors return `{ detail, code, field? }`. Add a translation for new codes under
  `errors.*` or `validation.*`.
- Use the SQLAlchemy ORM / bound parameters; never build SQL strings.
- Modals only for important or irreversible actions; toasts for non-critical success.
- Keep dependencies minimal. Add tests for new backend rules.
