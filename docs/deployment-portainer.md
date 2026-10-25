# Deploying OfficeHub with Portainer

OfficeHub is published as two Docker images on the GitHub Container Registry:

| Image | Purpose |
| --- | --- |
| `ghcr.io/letsmanu/officehub-frontend` | Web interface (nginx), port 8080, forwards `/api` to the backend |
| `ghcr.io/letsmanu/officehub-backend` | API (FastAPI), SQLite database and uploaded files in `/data` |

Both images are built for `linux/amd64` and `linux/arm64` (e.g. Raspberry Pi 4/5).
Each release has the tags `1.2.3`, `1.2` and `latest`.

## 1. Allow Portainer to download the images

The repository is private, so its images are private too. Choose **one** option:

**Option A – registry login (recommended for private images)**

1. On GitHub: profile picture → **Settings → Developer settings → Personal access tokens → Tokens (classic)**
   → **Generate new token (classic)** with only the scope **`read:packages`**. Copy the token.
2. In Portainer: **Registries → Add registry → Custom registry**
   - Name: `GitHub`
   - Registry URL: `ghcr.io`
   - Authentication: on, Username: your GitHub user name, Password: the token
3. Save.

**Option B – make the images public**

On GitHub: your profile → **Packages** → `officehub-backend` → **Package settings → Change visibility → Public**.
Repeat for `officehub-frontend`. The source code stays private; only the built images become downloadable.

## 2. Create the stack

1. Download `docker-compose.yml` and `stack.env` from the
   [latest release](https://github.com/LetsManu/officehub/releases/latest).
2. In Portainer: **Stacks → Add stack**
   - Name: `officehub`
   - Build method: **Web editor** – paste the content of `docker-compose.yml`
     (or **Repository**: repository URL `https://github.com/LetsManu/officehub`, reference `refs/heads/main`,
     **Compose path `deploy/portainer/docker-compose.yml`**, and authentication with your GitHub user + token
     because the repository is private)
3. **Environment variables → Load variables from .env file** → choose `stack.env`. Then set at least:

   | Variable | What to enter |
   | --- | --- |
   | `ADMIN_EMAIL` | Email address of the first administrator |
   | `ADMIN_PASSWORD` | A strong password (change it after the first sign-in) |
   | `FRONTEND_PORT` | Port on the server, default `8080` |
   | `OFFICEHUB_VERSION` | Version to run, e.g. `1.0.0` (pinned in the release file) |
   | `COOKIE_SECURE` | `true` if users reach OfficeHub via HTTPS |

   Optional:

   | Variable | What to enter |
   | --- | --- |
   | `TIMEZONE` | Time zone for time tracking, default `Europe/Vienna` |
   | `PORTAL_URL` | Address people open, e.g. `https://officehub.example.com` – used for links in e-mails |
   | `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Your own mail server for e-mail notifications. Leave `SMTP_HOST` empty to switch e-mail off. Check it under **Administration → Security → Send a test e-mail to me**. |

   For a test installation with fictional people and data, set `DEMO_MODE=true` instead
   (all demo accounts use the password `demo1234` – never use demo mode in production).
4. **Deploy the stack.** After about 15 seconds open `http://<your-server>:8080` and sign in.

The administrator is created only on the very first start, when the database is still empty.
Changing `ADMIN_EMAIL` / `ADMIN_PASSWORD` later has no effect – use **Profile → Change password** instead.

## Office editing and meetings – nothing to set up

- **Word, Excel and PowerPoint in the browser**: the `craft` container starts with the portal, and OfficeHub finds
  it by itself. Word files open in **WordCraft**, PowerPoint files in **DeckCraft** and Excel files in **GridCraft**
  (open-source programs in the browser, a few MB of RAM); Save puts them back as a new version, and several people can
  edit the same file together live.
- **Video meetings and calls** run on the stack's own **Jitsi Meet** server (`jitsi-*` containers, about 1–2 GB of
  RAM). The `turn` container is a relay of your own for people on other networks (home office, mobile data). The
  short-lived `hostip` container finds the server's address in the office network (from its routing table) and
  stops; the public address comes from `PORTAL_URL` (or `PUBLIC_IP`, or the name people open the portal with). No
  outside service is used. **Set `PORTAL_URL`** to the address people use (e.g. `https://office.example.com`). Open these ports
  to the server for people outside the office: **UDP 10000** (Jitsi), **UDP+TCP 3478** and **UDP 49160–49200**
  (relay). Without the `jitsi-*` containers meetings run built in (directly between the browsers, through the relay
  when needed). Browsers only allow camera and microphone on **HTTPS** pages (see step 3).

### Optional extras

Add them to `COMPOSE_PROFILES` (e.g. `onlyoffice`) and redeploy. Passwords between OfficeHub and
these servers are made on the first start – there is nothing to type in.

| Profile | What it adds |
| --- | --- |
| `onlyoffice` | **ONLYOFFICE Docs** as a second editor (2–4 GB of RAM, first start takes a few minutes). HR chooses which one opens office files under **Administration → Office editing**. |

**Network drive and desktop programs (WebDAV):** always on, nothing to install on the server. Everyone creates an
**app password** under **Profile → Programs and network drive** and connects `https://<portal>/dav/` in Windows
Explorer (**Map network drive**), macOS Finder (**Go → Connect to server**) or a Linux file manager. The desktop
versions of WordCraft and DeckCraft, LibreOffice or Microsoft Office then open and save files of the spaces directly;
every save is a new version, and a file checked out by someone else cannot be overwritten. Windows needs HTTPS for this.

**People outside the office (home office, mobile data):** open the ports above. If `PORTAL_URL`'s name resolves to an
internal address only, set `PUBLIC_IP`. Behind **Cloudflare** (orange cloud) or a similar proxy the name resolves to
the proxy, which does not pass audio and video: OfficeHub notices that by itself (it asks its own portal address who
it is) and gives the meeting servers the office's real public address – nothing to set up, ports above still needed.
It looks again every ten minutes: with a changing (dynamic) address from the internet provider, the meeting servers
restart by themselves a minute after it changes.
`ICE_SERVERS` (with `ICE_USERNAME`, `ICE_PASSWORD`) replaces the relay with a
STUN/TURN server of your own.

**Windows and Android apps:** every release has `OfficeHub-Setup.exe` and `OfficeHub.apk` attached; people find
them in OfficeHub under **Install as app**. Nothing to set up on the server. Sign-ins from the apps last
`APP_SESSION_DAYS` (default 90) and are extended while used; `APP_DOWNLOAD_URL` points the download buttons
elsewhere (e.g. your own file share). The Android app keeps its own connection to OfficeHub for notifications and
calls (`GET /api/me/feed`), so no Google or Microsoft push service is involved. For your own builds see `apps/README.md`.

**Everything is a normal OfficeHub API.**
`POST /api/meetings/{id}/join` and `POST /api/calls` return the connection details (built in: a ticket for
`/api/rtc`; Jitsi: conference, token and server address), and `GET /api/calls/incoming` lists ringing calls.

## 3. HTTPS

Run OfficeHub behind your existing reverse proxy (Nginx Proxy Manager, Traefik, Caddy …):

- Forward your domain to `http://<server>:8080` (or join the proxy's Docker network and use `frontend:8080`).
- Set `COOKIE_SECURE=true` in the stack and redeploy.
- Allow uploads of at least 20 MB in the proxy (`client_max_body_size 20m` for nginx).

## Company login (Authentik, Keycloak …) – optional

People can sign in with their company account from your own OpenID Connect server. Example for **Authentik**:

1. Authentik → **Applications → Create with provider** → name `OfficeHub`, provider type **OAuth2/OpenID Provider**,
   client type **Confidential**, redirect URI (strict) `https://<officehub address>/api/auth/sso/callback`
   (OfficeHub shows the exact address under **Administration → Company login**). Keep the default scopes
   `openid`, `email`, `profile`.
2. Copy **Client ID**, **Client Secret** and the **OpenID Configuration Issuer**
   (`https://<authentik>/application/o/officehub/`) from the provider.
3. OfficeHub → **Administration → Company login**: paste them, tick **Turn on** and save (OfficeHub checks that it can
   reach the server). Optional: Authentik group names that make people HR / admins or managers.

New people are created as employees at their first sign-in (can be turned off). Existing accounts are linked by
e-mail address when the server confirms the address. Signing in with e-mail and password keeps working, so an
administrator can always get in. Someone deactivated in Authentik can no longer sign in; deactivate them in OfficeHub
too to end open sessions at once.

## 4. Updating

1. Stacks → `officehub` → **Editor**: change `OFFICEHUB_VERSION` to the new version (or keep `latest`).
2. Click **Update the stack** and enable **Re-pull image and redeploy**.

Your data stays in the `officehub_officehub-data` volume during updates.

**From 3.8 or older to 3.9:** the stack no longer has a `collabora` service (Word, Excel and PowerPoint files open in
the `craft` container: WordCraft, GridCraft and DeckCraft). Replace the stack's compose text with the new
`docker-compose.yml` of the release and tick **Prune services** when you update, so the old Collabora container goes
away. Files, versions and settings stay.
Read the release notes first, and make a backup before larger updates.

## 5. Backup

OfficeHub backs itself up: every night (from 2:00, also when the server was off at that time) the database and all
files go into one archive `officehub-YYYYMMDD-HHMMSS.tar.gz`. The newest 14 are kept. Under **Administration →
Backups** you see whether the last one worked, change time and number, back up now, download an archive or restore
one (the state before is backed up first).

The archives go to their own volume `officehub_officehub-backups`. To keep them off the server, mount a NAS share on
the Docker host and set `BACKUP_PATH` in the stack, e.g. `BACKUP_PATH=/mnt/nas/officehub-backups`. The folder must
be writable for user ID 1000 (`chown 1000 /mnt/nas/officehub-backups`).

To restore on a new server: deploy the stack, copy an archive into the backup folder and choose it under
**Administration → Backups**.

## Notes

- Use **standalone Docker** (not Swarm) stacks: the frontend waits for the backend health check via `depends_on`.
- The API port 8000 is not published by default. Uncomment the `ports` section of the backend if you need it.
- No internet access is required at runtime – only to download the images. Meetings stay on your server too. E-mail uses only the mail server you configure.

## Troubleshooting

| Problem | Cause and fix |
| --- | --- |
| "The office server cannot be reached" | The ONLYOFFICE container is not running or still starting (about a minute after a redeploy). Look at its log in Portainer. |
| Camera and microphone cannot be chosen | The portal is opened over plain `http://`. Use HTTPS. |
| Meeting opens, but nobody sees or hears the others | Built in: the people are in different networks – see "People outside the office". Or: the ports for meetings (UDP 10000, 3478, 49160–49200) are not open to the server, or `PORTAL_URL` does not resolve to its public address (set `PUBLIC_IP`). Behind Cloudflare: update to 3.9.1 or newer, which finds the real address by itself. |
| "Could not connect to the meeting" | With Jitsi: the reverse proxy does not pass WebSockets (Nginx Proxy Manager: *Websockets Support*). |
| The editor stays empty | Your reverse proxy must pass WebSockets and send `X-Forwarded-Proto` (all common ones do). |
| `No such image: officehub-backend:latest` | The stack uses an old copy of the repository's root `docker-compose.yml` that only builds from source. Use `deploy/portainer/docker-compose.yml` (or the release asset), or update to the latest root file, which now points to the published images |
| `pull access denied` / `unauthorized` | Images are private and Portainer has no registry login → step 1 |
| `Bind for 0.0.0.0:8080 failed` | Port is in use → choose another `FRONTEND_PORT` |
| Frontend stays in "created" state | Backend is not healthy yet → check the backend logs in Portainer |
| Cannot sign in after deployment | Admin was created by an earlier start with other values → use those, or remove the volume to start fresh (deletes all data) |
| Sign-in works but you are logged out at once | `COOKIE_SECURE=true` while using plain `http://` → set it to `false` or use HTTPS |
