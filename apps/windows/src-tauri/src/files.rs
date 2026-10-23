//! The OfficeHub folder in Explorer (like OneDrive): starts the sync (`sync/`) with an app password the portal made
//! for this computer, keeps that password protected by Windows (DPAPI, only this Windows user can read it), and
//! connects the sync to the tray menu and notifications.

use std::path::PathBuf;
use std::sync::{Arc, Mutex, OnceLock};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager};

use crate::sync::{self, engine::Event, engine::Words, Status};
use crate::texts;

#[derive(Default, Serialize, Deserialize, Clone)]
struct SyncSettings {
    server: String,
    login: String,
    /// The app password, protected with DPAPI (base64 of the protected bytes)
    secret: String,
    paused: bool,
}

static RUNNING: OnceLock<Mutex<Option<sync::Running>>> = OnceLock::new();
static STATUS: OnceLock<Mutex<Option<Status>>> = OnceLock::new();
/// What did not reach the server lately, newest first (shown in the portal's Files page)
static PROBLEMS: OnceLock<Mutex<Vec<Value>>> = OnceLock::new();
const PROBLEMS_KEPT: usize = 20;

fn running() -> &'static Mutex<Option<sync::Running>> {
    RUNNING.get_or_init(|| Mutex::new(None))
}

fn config_dir(app: &AppHandle) -> Option<PathBuf> {
    app.path().app_config_dir().ok()
}

fn settings_file(app: &AppHandle) -> Option<PathBuf> {
    config_dir(app).map(|d| d.join("sync.json"))
}

fn load(app: &AppHandle) -> Option<SyncSettings> {
    let text = std::fs::read_to_string(settings_file(app)?).ok()?;
    serde_json::from_str(&text).ok()
}

fn store(app: &AppHandle, settings: &SyncSettings) {
    if let Some(file) = settings_file(app) {
        if let Some(dir) = file.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        if let Ok(text) = serde_json::to_string_pretty(settings) {
            let _ = std::fs::write(file, text);
        }
    }
}

/// The sync folder: C:\Users\<name>\OfficeHub
pub fn folder() -> PathBuf {
    let home = std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    home.join("OfficeHub")
}

fn device() -> String {
    std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .unwrap_or_else(|_| "PC".into())
}

fn label(key: &str) -> String {
    texts::for_system()
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or(key)
        .to_string()
}

// ---------- the password, protected by Windows ----------

#[cfg(windows)]
#[allow(unsafe_code)]
fn protect(data: &[u8], unprotect: bool) -> Option<Vec<u8>> {
    use windows::Win32::Foundation::{LocalFree, HLOCAL};
    use windows::Win32::Security::Cryptography::{
        CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };
    let input = CRYPT_INTEGER_BLOB { cbData: u32::try_from(data.len()).ok()?, pbData: data.as_ptr() as *mut u8 };
    let mut output = CRYPT_INTEGER_BLOB::default();
    // SAFETY: input points to `data` for the call; output is allocated by Windows and freed with LocalFree
    unsafe {
        let done = if unprotect {
            CryptUnprotectData(&input, None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, &mut output)
        } else {
            CryptProtectData(&input, windows::core::w!("OfficeHub"), None, None, None, CRYPTPROTECT_UI_FORBIDDEN, &mut output)
        };
        done.ok()?;
        let bytes = std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        let _ = LocalFree(Some(HLOCAL(output.pbData.cast())));
        Some(bytes)
    }
}

#[cfg(not(windows))]
fn protect(data: &[u8], _unprotect: bool) -> Option<Vec<u8>> {
    // Only for trying the app on Linux/macOS: kept as is (Windows protects it per user)
    Some(data.to_vec())
}

fn hex(data: &[u8]) -> String {
    data.iter().map(|b| format!("{b:02x}")).collect()
}

fn unhex(text: &str) -> Option<Vec<u8>> {
    (0..text.len())
        .step_by(2)
        .map(|i| text.get(i..i + 2).and_then(|h| u8::from_str_radix(h, 16).ok()))
        .collect()
}

// ---------- start, stop, pause ----------

/// Starts the sync if this computer has been set up for it (and the portal address is the same).
pub fn start(app: &AppHandle, server: &str) {
    let Some(settings) = load(app) else { return };
    if settings.server != server || settings.secret.is_empty() {
        return;
    }
    let Some(password) = unhex(&settings.secret).and_then(|p| protect(&p, true)).and_then(|p| String::from_utf8(p).ok())
    else {
        return;
    };
    let Some(state_file) = config_dir(app).map(|d| d.join("sync-state.json")) else { return };
    let config = sync::Config {
        server: settings.server.clone(),
        login: settings.login.clone(),
        password,
        root: folder(),
        state_file,
        device: device(),
        display_name: "OfficeHub".into(),
        words: Words { conflict: label("syncConflictWord") },
    };
    let handle = app.clone();
    let report: sync::Report = Arc::new(move |status, event| {
        if let Some(status) = status {
            show_status(&handle, status);
        }
        if let Some(event) = event {
            tell(&handle, event);
        }
    });
    match sync::start(config, report) {
        Ok(run) => {
            run.pause(settings.paused);
            *running().lock().unwrap_or_else(|e| e.into_inner()) = Some(run);
        }
        Err(e) => eprintln!("OfficeHub sync could not start: {e}"),
    }
}

pub fn stop() {
    running().lock().unwrap_or_else(|e| e.into_inner()).take();
}

pub fn is_set_up(app: &AppHandle, server: &str) -> bool {
    load(app).is_some_and(|s| s.server == server && !s.secret.is_empty())
}

/// The portal made an app password for this computer: keep it protected and start.
pub fn set_up(app: &AppHandle, server: &str, login: &str, password: &str) {
    let Some(protected) = protect(password.as_bytes(), false) else { return };
    store(app, &SyncSettings { server: server.into(), login: login.into(), secret: hex(&protected), paused: false });
    stop();
    start(app, server);
    let _ = tauri_plugin_opener::open_path(folder().to_string_lossy().to_string(), None::<&str>);
}

/// Pause or continue (tray menu). Returns the new state.
pub fn toggle_pause(app: &AppHandle) -> bool {
    let Some(mut settings) = load(app) else { return false };
    settings.paused = !settings.paused;
    store(app, &settings);
    if let Some(run) = running().lock().unwrap_or_else(|e| e.into_inner()).as_ref() {
        run.pause(settings.paused);
    }
    settings.paused
}

pub fn is_paused(app: &AppHandle) -> bool {
    load(app).is_some_and(|s| s.paused)
}

/// Compare the folder now (the portal's "Sync now").
pub fn sync_now() {
    if let Some(run) = running().lock().unwrap_or_else(|e| e.into_inner()).as_ref() {
        run.now();
    }
}

/// Where the files are, how the sync is doing and what did not work – for the portal's Files page.
pub fn status_json(app: &AppHandle, server: Option<&str>) -> Value {
    let status = match STATUS.get_or_init(|| Mutex::new(None)).lock().unwrap_or_else(|e| e.into_inner()).clone() {
        Some(Status::Syncing) => "syncing",
        Some(Status::UpToDate) => "upToDate",
        Some(Status::Offline) => "offline",
        Some(Status::SignInNeeded) => "signIn",
        Some(Status::Paused) => "paused",
        None => "starting",
    };
    let set_up = server.is_some_and(|s| is_set_up(app, s));
    let problems = PROBLEMS.get_or_init(|| Mutex::new(Vec::new())).lock().unwrap_or_else(|e| e.into_inner()).clone();
    serde_json::json!({
        "folder": folder().to_string_lossy(),
        "setUp": set_up,
        "running": running().lock().unwrap_or_else(|e| e.into_inner()).is_some(),
        "paused": is_paused(app),
        "status": if set_up { status } else { "off" },
        "problems": problems,
        "error": sync::LAST_ERROR.lock().unwrap_or_else(|e| e.into_inner()).clone(),
    })
}

pub fn open_folder() {
    let _ = tauri_plugin_opener::open_path(folder().to_string_lossy().to_string(), None::<&str>);
}

/// Another portal (or "Connect to another OfficeHub"): stop, forget the password; the files stay.
pub fn forget(app: &AppHandle) {
    stop();
    if let Some(settings) = load(app) {
        #[cfg(windows)]
        {
            let _ = crate::sync::cloud::unregister(&settings.login);
        }
        let _ = settings;
    }
    if let Some(file) = settings_file(app) {
        let _ = std::fs::remove_file(file);
    }
    if let Some(dir) = config_dir(app) {
        let _ = std::fs::remove_file(dir.join("sync-state.json"));
    }
}

fn show_status(app: &AppHandle, status: Status) {
    let changed = {
        let mut current = STATUS.get_or_init(|| Mutex::new(None)).lock().unwrap_or_else(|e| e.into_inner());
        let changed = current.as_ref() != Some(&status);
        *current = Some(status.clone());
        changed
    };
    if !changed {
        return;
    }
    let key = match status {
        Status::Syncing => "syncSyncing",
        Status::UpToDate => "syncUpToDate",
        Status::Offline => "syncOffline",
        Status::SignInNeeded => "syncSignIn",
        Status::Paused => "syncPaused",
    };
    crate::set_tray_status(app, &label(key));
    crate::push_sync_status(app);
    if status == Status::SignInNeeded {
        // The app password was removed in the portal: the portal makes a new one at the next sign-in
        stop();
        if let Some(mut settings) = load(app) {
            settings.secret.clear();
            store(app, &settings);
        }
    }
}

fn tell(app: &AppHandle, event: Event) {
    let problem = match &event {
        Event::NotSupported { name } => Some(("type", name)),
        Event::OutsideSpace { name } => Some(("outside", name)),
        Event::ReadOnly { name } => Some(("readOnly", name)),
        Event::TooLarge { name } => Some(("tooLarge", name)),
        Event::UploadFailed { name } => Some(("failed", name)),
        Event::Busy { name } => Some(("busy", name)),
        Event::NewSpaceFolder { name } => Some(("newSpace", name)),
        _ => None,
    };
    if let Some((kind, name)) = problem {
        let at = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
        let mut list = PROBLEMS.get_or_init(|| Mutex::new(Vec::new())).lock().unwrap_or_else(|e| e.into_inner());
        list.retain(|p| p.get("name").and_then(Value::as_str) != Some(name.as_str()));
        list.insert(0, serde_json::json!({ "kind": kind, "name": name, "at": at }));
        list.truncate(PROBLEMS_KEPT);
    }
    let (title, body) = match event {
        Event::Conflict { name, copy } => {
            (label("syncConflictTitle"), label("syncConflictBody").replace("{name}", &name).replace("{copy}", &copy))
        }
        Event::NotSupported { name } => (label("syncUnsupportedTitle"), label("syncUnsupportedBody").replace("{name}", &name)),
        Event::Busy { name } => (label("syncBusyTitle"), label("syncBusyBody").replace("{name}", &name)),
        Event::ManyDeletes { count } => {
            (label("syncDeletesTitle"), label("syncDeletesBody").replace("{count}", &count.to_string()))
        }
        Event::NewSpaceFolder { name } => (label("syncNewSpaceTitle"), label("syncNewSpaceBody").replace("{name}", &name)),
        Event::OutsideSpace { name } => (label("syncOutsideTitle"), label("syncOutsideBody").replace("{name}", &name)),
        Event::ReadOnly { name } => (label("syncReadOnlyTitle"), label("syncReadOnlyBody").replace("{name}", &name)),
        Event::TooLarge { name } => (label("syncTooLargeTitle"), label("syncTooLargeBody").replace("{name}", &name)),
        Event::UploadFailed { name } => (label("syncFailedTitle"), label("syncFailedBody").replace("{name}", &name)),
    };
    crate::notify(app, &title, &body, Some("/files".into()));
    crate::push_sync_status(app);
}

#[cfg(test)]
mod tests {
    #[test]
    fn hex_round_trips() {
        let data = [0u8, 15, 16, 255];
        assert_eq!(super::unhex(&super::hex(&data)), Some(data.to_vec()));
        assert_eq!(super::unhex("zz"), None);
    }
}
