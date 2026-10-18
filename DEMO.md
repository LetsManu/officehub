# OfficeHub – live demo script (5–10 minutes)

**Setup before the audience arrives**

```bash
docker compose down -v && docker compose up -d   # fresh demo data
```

- Open <http://localhost:8080> in a browser window at 100 % zoom (a second, private window helps for switching people).
- Have the GitHub repository open in a second tab, with the demo issues already created.
- Demo password for every account: `demo1234`. The sign-in page lists all demo accounts – one click signs in.

---

## 1. Opening (30 seconds)

> "This is a simple employee portal that Claude Code built. It handles the everyday office things –
> vacation, expenses, new equipment, company documents and news – in one calm place.
> It runs on our own server with one command, works offline, and it has no AI inside.
> The AI part was only the building."

## 2. Dashboard walkthrough (1 minute)

Sign in as **Anna Mayer** (Marketing, employee).

- Point out the greeting with her first name and the four quick actions:
  *Request vacation, Submit expense, Request equipment, Find documents*.
- "Anna sees only what matters today: her open request and the latest news. No charts, no clutter."
- Show the pinned announcement and the upcoming team meeting.
- Optional: open the menu on a phone-sized window to show the mobile layout.

## 3. Vacation request (2 minutes)

1. Click **Urlaub beantragen / Request vacation**.
2. Click **Continue to review** without filling anything → inline messages: *"Please select a start date."*
3. Choose an end date *before* the start date → *"End date must be after the start date."*
4. Pick a Monday to Friday → the box shows **5 working days**, calculated live.
5. Add a reason (optional), click **Continue to review**, show the summary, then **Send request**.
6. Show the confirmation and click **View request**: clear status card *Submitted*, comments and history behind expandable sections.

> "Short form, sensible defaults, a review step for important requests, and a clear confirmation."

## 4. Approval workflow (2 minutes)

Sign out (sidebar) and sign in as **Tom Huber** (manager).

1. The dashboard says *"3 requests are waiting for your decision"* → **Review now**.
2. The approvals list shows Anna's new vacation. Open **Filters** to show type, person and date filters.
3. Open the request → **Approve** → a dialog asks for confirmation with an optional comment ("Enjoy your time off!").
   Mention: Escape closes it, focus stays inside, the keyboard works everywhere.
4. Toast: *Request approved*. The status card turns green.
5. Open the Ubuntu laptop request (*In review*) → **Reject** → the dialog asks for a reason.
6. Go to **Administration**: four simple figures and **Download CSV** for approved requests.

Optional: switch back to Anna to show the approved request with Tom's comment.

## 5. Document search (1 minute)

As any person, open **Documents**.

- Type `25` or `Urlaubstage` / `vacation days` → the vacation policy is found **by its content**, with the matching sentence highlighted.
- Filter by category, open the document: it is readable directly in the browser, or downloadable.

## 6. Announcements (1 minute)

Sign in as **Julia Weber** (HR / Admin) → **Manage announcements** → **New announcement**.

- Title "Summer party", category *Event*, pick an event date, tick **Pin to top** → **Publish**.
- "Publish and expiry dates are tucked away under *More settings* – most people never need them."
- Open **Dashboard** → the new event shows up in *Upcoming events*.

## 7. GitHub issue → pull request with Claude Code (2 minutes)

In the GitHub repository:

1. Open one of the prepared issues (see below), e.g. *"Show a Today badge for events happening today"*.
2. Add a comment: `@claude please implement this issue`.
3. The **Claude Code** workflow starts (Actions tab). Claude reads the code, makes the change, runs the tests,
   pushes a branch and replies with a link to create the pull request.
4. Open the pull request and show the small, readable diff plus green CI.

> "The same assistant that built the portal can now maintain it from normal GitHub issues –
> the team stays in control by reviewing every pull request."

If the run takes too long, show a pull request from a rehearsal run instead (see fallback plan).

## 8. Closing (30 seconds)

> "OfficeHub is a complete, self-hosted portal: guided requests, approvals, documents and news,
> in German and English, accessible and mobile-friendly. One `docker compose up` and it runs on our own hardware –
> no cloud and no AI in the product. Claude Code helped build it in a short time, and it can keep improving it
> through ordinary GitHub issues."

---

## Prepared issues for the live demo

1. **Show a "Today" badge for events happening today** – on the dashboard *Upcoming events* card, mark events whose date is today.
2. **Add "Parking space" as an equipment category** – new option in the equipment form, translated in German and English.
3. **Sort documents by last updated** – add a sort option (A–Z / newest first) to the documents page.

## Fallback plan

| Problem | What to do |
| --- | --- |
| Docker does not start | Run the backend and frontend locally (see README → Local development) or show the screenshots in `docs/screenshots/`. |
| Demo data is messed up | `docker compose down -v && docker compose up -d` (about 10 seconds). |
| Port 8080 is busy | Set `FRONTEND_PORT=8081` in `.env` and restart. |
| No internet in the room | OfficeHub runs fully offline – only the GitHub part needs internet. Build the images beforehand. |
| Claude Code action is slow or fails | Show the pull request from the rehearsal run and its diff; explain the workflow in `.github/workflows/claude.yml`. |
| Sign-in fails | Use the demo account buttons; password `demo1234`. Wait 15 minutes or restart the backend after 10 failed attempts. |
