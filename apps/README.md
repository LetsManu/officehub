# OfficeHub apps

Both apps show the company's own OfficeHub (nothing of the portal is bundled) and add what a browser tab can't.
The portal talks to them through `frontend/src/lib/native.ts`; only the company's address is allowed to.

| | Windows (`windows/`) | Android (`android/`) |
|---|---|---|
| Built with | Tauri 2 (Rust, WebView2) | Kotlin, Android WebView, Material You |
| First start | asks for the OfficeHub address (`ui/index.html`) | asks for the address (`ConnectActivity`) |
| Notifications | Windows toasts while it runs (window closed = tray) | `FeedService` waits on `GET /api/me/feed`, also when closed |
| Calls | small ringing window bottom right | full screen over the lock screen (`CallActivity`) |
| Number on icon | taskbar overlay | Android notification dots |
| Other | autostart, tray menu, single instance, remembers size | camera/mic, file upload/download, back button |

Sign-ins from the apps (`OfficeHubApp/` in the user agent) last `APP_SESSION_DAYS` (default 90) and are extended
while used (backend `routers/auth.py`, `deps.py`).

## Building

`.github/workflows/apps.yml` builds both on pull requests that touch them and attaches `OfficeHub-Setup.exe` and
`OfficeHub.apk` to every release.

- **Windows** (on Windows, with Rust and Node): `cd windows && npm ci && npx tauri build` →
  `src-tauri/target/release/bundle/nsis/*-setup.exe`. `cargo test` in `src-tauri` runs the unit tests; on Linux the
  same code runs with WebKitGTK for trying things out.
  Code signing (cloud): Azure Trusted Signing with the secrets `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`,
  `AZURE_TENANT_ID` and the variables `WINDOWS_SIGNING_ENDPOINT`, `WINDOWS_SIGNING_ACCOUNT`, `WINDOWS_SIGNING_PROFILE`;
  any other provider with the secret `WINDOWS_SIGN_COMMAND` (signs `%1`, credentials in `WINDOWS_SIGN_SECRET_1…3`).
  The workflow checks the signature of the installer.
- **Android** (JDK 17, Android SDK): `cd android && ./gradlew testDebugUnitTest lintDebug assembleRelease`.
  Release signing: set `ANDROID_KEYSTORE_FILE`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`
  (in GitHub: the secrets `ANDROID_KEYSTORE_BASE64` and the three others). Without them the APK is signed with a
  debug key: it installs, but an update then needs the old app removed first.
