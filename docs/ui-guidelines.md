# OfficeHub – UI guidelines

OfficeHub should feel **calm, trustworthy and company-ready**. Every screen serves one task,
shows only the information needed for it, and puts the most common action within reach.

All values below are defined as CSS custom properties in `frontend/src/styles.css`.
Use the tokens, never hard-coded colours.

## Principles

1. **One task per screen.** Remove anything that does not help with it.
2. **Progressive disclosure.** Rare options go into expandable sections (`<details class="disclosure">`),
   secondary pages or dialogs – for example *More settings*, *Filters*, *History*.
3. **Plain language.** Write for someone who has never used the portal. No technical terms.
4. **Most common action first.** Primary button on the right of a button row, quick actions on the dashboard.
5. **Never a dead end.** Every empty list explains what will appear and offers a next step.

## Colours

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--color-bg` | `#F5F6F8` | `#0F1216` | Page background |
| `--color-surface` | `#FFFFFF` | `#171B21` | Cards, sidebar, dialogs |
| `--color-border` | `#E1E4E9` | `#2A313B` | Subtle borders and dividers |
| `--color-text` | `#1F2937` | `#E6E8EB` | Body text |
| `--color-text-muted` | `#4B5563` | `#B2B8C2` | Secondary text, labels |
| `--color-primary` | `#1D4ED8` | `#2F5FE0` | Brand blue: primary buttons, active navigation, links |
| `--color-success` | `#15803D` | `#4ADE80` | **Only** success / approved |
| `--color-warning` | `#B45309` | `#FBBF24` | **Only** warnings / in review |
| `--color-danger` | `#B91C1C` | `#F87171` | **Only** errors and destructive actions |

Each semantic colour has a soft background variant (`--color-*-soft`) for badges and notices.

- All normal text meets a contrast ratio of at least **4.5:1** against its background.
- Never use colour alone to carry meaning: status badges always include the word, errors include an icon and text.
- No gradients, no decorative colours.

## Typography

- System font stack (`system-ui, -apple-system, Segoe UI, Roboto, …`) – no web fonts, works offline.
- Base size **16 px**, line height 1.55.

| Token | Size | Use |
| --- | --- | --- |
| `--text-2xl` | 28 px | Page title (`h1`) |
| `--text-xl` | 22 px | Dialog title |
| `--text-lg` | 18 px | Section title (`h2`) |
| `--text-md` | 16 px | Body |
| `--text-sm` | 14 px | Labels, buttons, meta information |
| `--text-xs` | 13 px | Badges, small captions |

One `h1` per page. Headings use weight 650; body text 400; labels and buttons 600.

## Spacing and shape

- Spacing scale: 4, 8, 12, 16, 24, 32, 48 px (`--space-1` … `--space-7`).
- Cards: 24 px padding, 14 px radius, 1 px border, **no heavy shadows** (shadows only for overlays).
- Inputs and buttons: 10 px radius, at least **44 × 44 px** touch target.
- Content width: forms max. 760 px, detail pages 860 px, lists use the full content column.
- Generous whitespace: 24 px between page sections.

## Buttons

| Level | Class | When |
| --- | --- | --- |
| Primary | `.btn-primary` | The main action of a screen or dialog. **At most one per area.** |
| Secondary | `.btn-secondary` | Alternative actions: *Save as draft*, *Change details*, *Cancel* in dialogs |
| Ghost | `.btn-ghost` | Low-emphasis actions in lists and headers: *Edit*, *All requests* |
| Danger | `.btn-danger` | Confirming a destructive action inside a dialog |
| Danger outline / ghost | `.btn-danger-outline` | Starting a destructive action on a page (*Reject*, *Cancel request*) |

- Button text says what happens: *Send request*, not *OK*.
- In a row, the primary button is last (right). On narrow screens dialog buttons stack full-width.
- Disable buttons while saving and change the text (*Saving …*).

## Status colours

| Status | Colour | Badge |
| --- | --- | --- |
| Draft | Neutral grey | `badge-draft` |
| Submitted | Blue (primary) | `badge-submitted` |
| In review | Amber (warning) | `badge-in_review` |
| Approved | Green (success) | `badge-approved` |
| Rejected | Red (danger) | `badge-rejected` |
| Cancelled | Neutral grey | `badge-cancelled` |

The request detail page repeats the status in a large **inline status card** with a one-sentence explanation.

## Choosing the right feedback

| Situation | Component |
| --- | --- |
| Non-critical success (saved, comment added) | **Toast** |
| Status of a request, results of validation, information that must stay visible | **Inline status card / notice** |
| Important or irreversible action (cancel, reject, archive, approve) | **Modal dialog** |
| Comments, history, filters, advanced settings | **Expandable section** |
| Missing or wrong input | **Inline field error** + summary notice at the top of the form |

## Modal rules

Use dialogs **only** for important or irreversible actions. Every dialog (`BaseModal.vue`) has:

- A clear title phrased as a question or action (*"Cancel this request?"*)
- A short explanation of the consequence
- A primary action and a cancel action with specific labels (*"Yes, cancel it"* / *"Keep request"*)
- A visible close button (×)
- **Escape** closes the dialog; clicking the backdrop closes it
- A focus trap: Tab stays inside the dialog
- Initial focus on the first field, or on the **safe** button for destructive dialogs
- Focus returns to the element that opened the dialog

## Toast rules

- Only for **non-critical** confirmations: *"Comment added."*, *"Draft saved."*
- Auto-dismiss after **5 seconds** (errors 6 seconds), with a close button.
- Announced to screen readers through an `aria-live="polite"` region.
- At most three at a time. Never put actions or essential information in a toast.

## Empty states

Every list has an empty state (`EmptyState.vue`) with:

- A neutral icon
- One or two sentences that explain **what will appear here and how**
- A clear call-to-action button when there is a sensible next step

> "No requests yet. When you submit a vacation, expense, or equipment request, it will appear here."
> **[Create your first request]**

Filtered lists say that nothing matches and offer **Reset filters** / **Clear search**.

## Error messages

- Say what is wrong **and** how to fix it, in one short sentence: *"End date must be after the start date."*
- Show field errors directly below the field, in red with an icon, linked via `aria-describedby`.
- Mark invalid fields with `aria-invalid="true"` and move focus to the first invalid field.
- Never blame the user, never show technical details (status codes, stack traces).
- Server errors use a stable `code` that the frontend translates (`errors.*`, `validation.*`).

## Writing

- Address people as *you* (German: *du*), friendly and professional.
- Short sentences. Verbs on buttons. Sentence case for titles.
- Use everyday words: *Request*, *Send*, *Approve* – not *Ticket*, *Submit payload*, *Workflow*.
- Every text exists in German (`de.ts`, default) and English (`en.ts`).

## Accessibility checklist

- Everything works with the keyboard; visible focus outline (3 px, brand colour).
- *Skip to content* link; one `main` landmark; navigation marks the current page with `aria-current`.
- Form fields have visible labels; hints and errors are connected with `aria-describedby`.
- Icons are decorative (`aria-hidden`) unless they carry meaning, then they get a label.
- Touch targets at least 44 × 44 px. Layout works from 320 px wide phones to large desktops.
- Respect `prefers-reduced-motion`.
