# OfficeHub – notes for Claude Code

OfficeHub is a self-hosted employee portal (requests, documents, announcements).
It must stay simple for non-technical office employees. **Never add AI features,
chatbots, external APIs or cloud dependencies to the application.**

## Layout

- `backend/` – FastAPI + SQLAlchemy + SQLite. Entry point `app/main.py`.
  - `app/routers/` – one module per API area; permission checks live here.
  - `app/services/requests.py` – request validation per type, permissions, serialization.
  - `app/seed.py` – first admin and fictional demo data (`DEMO_MODE=true`).
  - `tests/` – pytest, uses demo data; run `python -m pytest -q` in `backend/`.
- `frontend/` – Vue 3 + Vite + TypeScript, no UI library.
  - `src/locales/de.ts` is the source of truth for UI text; `en.ts` must have the same keys.
  - `src/components/` – shared building blocks (BaseModal, FormField, EmptyState, StatusBadge …).
  - `src/styles.css` – design tokens. Follow `docs/ui-guidelines.md`.
  - Run `npm test` (translations + logic) and `npm run build` (includes type check).

## Conventions

- Every UI string goes through `t('…')` in **both** `de.ts` and `en.ts`. Use plain, friendly
  language without technical terms (see `docs/ui-guidelines.md` → Writing).
- Show user content with `{{ }}` interpolation only. `v-html` is allowed only with
  `renderMarkdown()` from `src/lib/markdown.ts`, which escapes HTML first.
- API errors return `{ detail, code, field? }`. Add a translation for new codes under
  `errors.*` or `validation.*`.
- Use the SQLAlchemy ORM / bound parameters; never build SQL strings.
- Modals only for important or irreversible actions; toasts for non-critical success.
- Keep dependencies minimal. Add tests for new backend rules.
