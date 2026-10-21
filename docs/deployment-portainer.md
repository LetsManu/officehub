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

- **Word, Excel and PowerPoint in the browser**: the stack starts **Collabora Online** with the portal, and OfficeHub
  finds it by itself. It is reached through the portal's own address (`/collabora/`), works with HTTP and HTTPS, and
  needs about 1 GB of RAM. Don't want it? Remove the `collabora` service from the stack.
- **Video meetings and calls** are built in: OfficeHub introduces the browsers to each other and audio and video go
  directly between them – no extra container. Good for calls and meetings of up to 8 people inside the office
  network. Browsers only allow camera and microphone on **HTTPS** pages (see step 3).

### Optional extras

Add them to `COMPOSE_PROFILES` (e.g. `jitsi` or `jitsi,onlyoffice`) and redeploy. Passwords between OfficeHub and
these servers are made on the first start – there is nothing to type in.

| Profile | What it adds |
| --- | --- |
| `jitsi` | A **Jitsi Meet** server for larger meetings. OfficeHub uses it by itself once it runs. Open **UDP port 10000** to the server; for people outside the office network also set `JITSI_PUBLIC_IP`. About 1–2 GB of RAM. |
| `onlyoffice` | **ONLYOFFICE Docs** as a second editor (2–4 GB of RAM, first start takes a few minutes). HR chooses the default under **Administration → Office editing**. |

**People outside the office (home office, mobile data):** with built-in meetings their browsers often cannot reach
each other directly. Either switch on `jitsi` with `JITSI_PUBLIC_IP`, or point `ICE_SERVERS` to a TURN server of your
own (e.g. `turn:turn.your-company.example:3478`, with `ICE_USERNAME` and `ICE_PASSWORD`).

**Desktop and phone apps later:** everything the web page uses is a normal OfficeHub API.
`POST /api/meetings/{id}/join` and `POST /api/calls` return the connection details (built in: a ticket for
`/api/rtc`; Jitsi: conference, token and server address), and `GET /api/calls/incoming` lists ringing calls.

## 3. HTTPS

Run OfficeHub behind your existing reverse proxy (Nginx Proxy Manager, Traefik, Caddy …):

- Forward your domain to `http://<server>:8080` (or join the proxy's Docker network and use `frontend:8080`).
- Set `COOKIE_SECURE=true` in the stack and redeploy.
- Allow uploads of at least 20 MB in the proxy (`client_max_body_size 20m` for nginx).

## 4. Updating

1. Stacks → `officehub` → **Editor**: change `OFFICEHUB_VERSION` to the new version (or keep `latest`).
2. Click **Update the stack** and enable **Re-pull image and redeploy**.

Your data stays in the `officehub_officehub-data` volume during updates.
Read the release notes first, and make a backup before larger updates.

## 5. Backup

All data lives in the volume `officehub_officehub-data` (`officehub.db` and the `uploads/` folder).

Using a shell on the Docker host:

```bash
docker stop officehub-backend-1
docker run --rm -v officehub_officehub-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/officehub-backup-$(date +%F).tar.gz -C /data .
docker start officehub-backend-1
```

Container and volume names can differ slightly depending on the stack name – check them under **Containers** and **Volumes** in Portainer.
To restore, stop the backend, extract the archive into the volume and start it again (see the README).

## Notes

- Use **standalone Docker** (not Swarm) stacks: the frontend waits for the backend health check via `depends_on`.
- The API port 8000 is not published by default. Uncomment the `ports` section of the backend if you need it.
- No internet access is required at runtime – only to download the images. Meetings stay on your server too. E-mail uses only the mail server you configure.

## Troubleshooting

| Problem | Cause and fix |
| --- | --- |
| "The office server cannot be reached" | The Collabora/ONLYOFFICE container is not running or still starting (about a minute after a redeploy). Look at its log in Portainer. |
| Camera and microphone cannot be chosen | The portal is opened over plain `http://`. Use HTTPS. |
| Meeting opens, but nobody sees or hears the others | Built in: the people are in different networks – see "People outside the office". With Jitsi: UDP port 10000 is blocked or `JITSI_PUBLIC_IP` is missing. |
| "Could not connect to the meeting" | With Jitsi: the reverse proxy does not pass WebSockets (Nginx Proxy Manager: *Websockets Support*). |
| Collabora stops right after starting with "Failed to listen" | The host has no IPv6. The compose file already sets `net.proto=IPv4`; keep that line if you copy the service. |
| The editor stays empty | Your reverse proxy must pass WebSockets and send `X-Forwarded-Proto` (all common ones do). |
| `No such image: officehub-backend:latest` | The stack uses an old copy of the repository's root `docker-compose.yml` that only builds from source. Use `deploy/portainer/docker-compose.yml` (or the release asset), or update to the latest root file, which now points to the published images |
| `pull access denied` / `unauthorized` | Images are private and Portainer has no registry login → step 1 |
| `Bind for 0.0.0.0:8080 failed` | Port is in use → choose another `FRONTEND_PORT` |
| Frontend stays in "created" state | Backend is not healthy yet → check the backend logs in Portainer |
| Cannot sign in after deployment | Admin was created by an earlier start with other values → use those, or remove the volume to start fresh (deletes all data) |
| Sign-in works but you are logged out at once | `COOKIE_SECURE=true` while using plain `http://` → set it to `false` or use HTTPS |
