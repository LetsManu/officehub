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

## Optional: edit Word, Excel and PowerPoint files in the browser

OfficeHub can use your own **Collabora Online** and/or **ONLYOFFICE Docs** server. Both are already in the compose
file and only run when you switch them on. They talk to OfficeHub inside the stack and are reached in the browser
through the portal's own address (`/collabora/` and `/onlyoffice/`) – no cloud service is involved.

In the stack's environment variables set:

| To use | Set |
| --- | --- |
| Collabora | `COMPOSE_PROFILES=collabora` and `COLLABORA_URL=http://collabora:9980` |
| ONLYOFFICE | `COMPOSE_PROFILES=onlyoffice`, `ONLYOFFICE_URL=http://onlyoffice` and a long random `ONLYOFFICE_JWT_SECRET` |
| Both | `COMPOSE_PROFILES=collabora,onlyoffice` and all of the above |

Also set `PORTAL_URL` to the address people use (Collabora only allows itself to be shown inside that page) and,
when people use HTTPS, `COLLABORA_SSL_TERMINATION=true`. Redeploy the stack. The first start of ONLYOFFICE takes a
minute or two. With both servers, HR chooses the default under **Administration → Office editing**; people can
switch at the top of the editor.

Plan for memory: Collabora needs about 1 GB of RAM, ONLYOFFICE about 2–4 GB.

## Optional: video meetings and calls

OfficeHub can hold video meetings and calls on your own **Jitsi Meet** server, with OfficeHub's own interface. The
four Jitsi containers are already in the compose file and only run when you switch them on. Browsers reach them
through the portal's own address (`/jitsi/`, `/colibri-ws/`); only the video and audio stream uses a separate port.

In the stack's environment variables set:

| Variable | Value |
| --- | --- |
| `COMPOSE_PROFILES` | add `jitsi`, e.g. `jitsi` or `collabora,jitsi` |
| `JITSI_APP_SECRET` | a long random text (OfficeHub and Jitsi share it to sign meeting tokens) |
| `JITSI_INTERNAL_PASSWORD` | another long random text (used only between the Jitsi containers) |
| `JITSI_PUBLIC_IP` | the server's public IP address, if people join from outside the office network |
| `PORTAL_URL` | the HTTPS address people use, e.g. `https://portal.your-company.example` |

Then:

1. **HTTPS is required.** Browsers only allow camera and microphone on HTTPS pages (see step 3). Your reverse proxy
   must also pass WebSockets (`Upgrade` / `Connection` headers) – Nginx Proxy Manager: switch on *Websockets Support*.
2. **Open UDP port 10000** to the Docker host in the firewall (and forward it on the router for people outside).
   The audio and video stream goes there directly; it does not pass the reverse proxy.
3. Redeploy the stack. **Meetings** appears in the menu, a call button in every chat and a meeting room in every space.

Plan for about 1–2 GB of RAM, more for many people at once. A guest link (optional per meeting) lets people from
outside join; they wait until someone in the meeting clicks **Let in**.

**Desktop and phone apps later:** everything the web page uses is a normal OfficeHub API.
`POST /api/meetings/{id}/join` and `POST /api/calls` return the conference name, a token and the server address,
and `GET /api/calls/incoming` lists ringing calls – a Windows or Android app can use them with the Jitsi SDKs.

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
| "The office server cannot be reached" | The Collabora/ONLYOFFICE container is not running (check `COMPOSE_PROFILES`) or still starting. Look at its log in Portainer. |
| "Video meetings are not set up yet" | `JITSI_APP_SECRET` is empty for the backend. Set it and redeploy. |
| Camera and microphone cannot be chosen | The portal is opened over plain `http://`. Use HTTPS. |
| Meeting opens, but nobody sees or hears the others | UDP port 10000 is blocked, or `JITSI_PUBLIC_IP` is missing/wrong for people outside. Check the `jitsi-jvb` log. |
| "Could not connect to the meeting" | The Jitsi containers are not running (check `COMPOSE_PROFILES`), `JITSI_APP_SECRET` differs between backend and Jitsi, or the reverse proxy does not pass WebSockets. |
| Collabora stops right after starting with "Failed to listen" | The host has no IPv6. The compose file already sets `net.proto=IPv4`; keep that line if you copy the service. |
| The editor stays empty or shows a security error | `PORTAL_URL` does not match the address in the browser, or `COLLABORA_SSL_TERMINATION` does not match HTTP/HTTPS. |
| `No such image: officehub-backend:latest` | The stack uses an old copy of the repository's root `docker-compose.yml` that only builds from source. Use `deploy/portainer/docker-compose.yml` (or the release asset), or update to the latest root file, which now points to the published images |
| `pull access denied` / `unauthorized` | Images are private and Portainer has no registry login → step 1 |
| `Bind for 0.0.0.0:8080 failed` | Port is in use → choose another `FRONTEND_PORT` |
| Frontend stays in "created" state | Backend is not healthy yet → check the backend logs in Portainer |
| Cannot sign in after deployment | Admin was created by an earlier start with other values → use those, or remove the volume to start fresh (deletes all data) |
| Sign-in works but you are logged out at once | `COOKIE_SECURE=true` while using plain `http://` → set it to `false` or use HTTPS |
