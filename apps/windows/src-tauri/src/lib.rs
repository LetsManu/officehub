//! OfficeHub for Windows: the company's OfficeHub in its own window, like Teams.
//!
//! The portal itself comes from the company's server (nothing is bundled but the address screen and the ringing
//! window in `ui/`). The app adds what a browser tab can't: it keeps running in the notification area when the
//! window is closed, starts with Windows, shows notifications from Windows itself (a click opens the right page),
//! puts the number of unread items on the taskbar icon and rings with its own small window when a call comes in.
//! Like Teams, the tray menu sets the status, the taskbar icon offers chat, calendar and meetings (jump list) and
//! flashes for new messages while the window is in the background.
//! The portal talks to it through `app_message` (frontend `src/lib/native.ts`); only the company's address gets
//! that permission.
#![recursion_limit = "256"] // the texts (texts.rs) are one large json! literal

use std::path::PathBuf;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::ipc::CapabilityBuilder;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::{MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};
use tauri::{
    AppHandle, Manager, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};

mod badge;
mod jumplist;
mod files;
pub mod sync;
mod texts;

/// The portal recognises the app by this (longer sign-in, see backend routers/auth.py).
const USER_AGENT: &str = concat!(
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0 OfficeHubApp/",
    env!("CARGO_PKG_VERSION"),
    " (windows)"
);

#[derive(Default, Serialize, Deserialize, Clone)]
struct Settings {
    /// The company's OfficeHub, e.g. "https://portal.firma.de/"
    server: Option<String>,
    /// Autostart was switched on once (the person may switch it off again in the tray menu)
    autostart_set: bool,
    /// "OfficeHub keeps running here" was shown once
    tray_hint_shown: bool,
}

#[derive(Default)]
struct AppState {
    settings: Mutex<Settings>,
    /// The call ringing in its own window
    ringing: Mutex<Option<i64>>,
    /// How many portal permissions were added (each needs its own name)
    grants: Mutex<u32>,
    tray: Mutex<Option<TrayIcon>>,
    /// The company login page (Authentik, Keycloak …): it opens in the app's window, not in the browser
    sign_in: Mutex<Vec<String>>,
    /// Unread items and the sync status, for the tray icon's tooltip
    unread: Mutex<i64>,
    sync_status: Mutex<String>,
}

fn settings_file(app: &AppHandle) -> Option<PathBuf> {
    app.path()
        .app_config_dir()
        .ok()
        .map(|dir| dir.join("settings.json"))
}

fn load_settings(app: &AppHandle) -> Settings {
    settings_file(app)
        .and_then(|path| std::fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

fn save_settings(app: &AppHandle, settings: &Settings) {
    if let Some(path) = settings_file(app) {
        if let Some(dir) = path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        if let Ok(text) = serde_json::to_string_pretty(settings) {
            let _ = std::fs::write(path, text);
        }
    }
}

fn state(app: &AppHandle) -> tauri::State<'_, AppState> {
    app.state::<AppState>()
}

/// "portal.firma.de" or "http://10.0.0.5:8080" → a full address ending in "/".
fn normalize(address: &str) -> Result<Url, String> {
    let trimmed = address.trim().trim_end_matches('/');
    if trimmed.is_empty() {
        return Err("empty".into());
    }
    let with_scheme = if trimmed.contains("://") {
        trimmed.to_string()
    } else {
        format!("https://{trimmed}")
    };
    let mut url = Url::parse(&with_scheme).map_err(|_| "invalid".to_string())?;
    if url.scheme() != "https" && url.scheme() != "http" {
        return Err("invalid".into());
    }
    url.set_path("/");
    url.set_query(None);
    url.set_fragment(None);
    Ok(url)
}

/// Is there an OfficeHub at this address? Its public settings name the version.
fn check_server(url: &Url) -> Result<Value, String> {
    let config = url.join("api/config").map_err(|_| "invalid".to_string())?;
    // The system's TLS (Schannel on Windows): company certificates from the Windows store are trusted as in Edge
    let tls = native_tls::TlsConnector::new().map_err(|_| "unreachable".to_string())?;
    let agent = ureq::AgentBuilder::new()
        .tls_connector(std::sync::Arc::new(tls))
        .build();
    let response = agent
        .get(config.as_str())
        .set("User-Agent", USER_AGENT)
        .timeout(std::time::Duration::from_secs(10))
        .call()
        .map_err(|_| "unreachable".to_string())?;
    let body: Value = response
        .into_json()
        .map_err(|_| "not_officehub".to_string())?;
    if body.get("version").is_some() && body.get("meetings_enabled").is_some() {
        Ok(body)
    } else {
        Err("not_officehub".into())
    }
}

/// The company login (OpenID Connect) named in the portal's public settings.
fn remember_sign_in(app: &AppHandle, config: &Value) {
    let origins: Vec<String> = config
        .pointer("/sso/origins")
        .and_then(Value::as_array)
        .map(|list| {
            list.iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();
    *state(app).sign_in.lock().unwrap_or_else(|e| e.into_inner()) = origins;
}

/// At every start: the company login may have been set up (or moved) since.
fn refresh_sign_in(app: &AppHandle) {
    let server = state(app)
        .settings
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .server
        .clone();
    let Some(url) = server.and_then(|s| Url::parse(&s).ok()) else {
        return;
    };
    let handle = app.clone();
    std::thread::spawn(move || {
        if let Ok(config) = check_server(&url) {
            remember_sign_in(&handle, &config);
        }
    });
}

fn origin_of(url: &Url) -> String {
    url.origin().ascii_serialization()
}

/// Only the company's own address may talk to the app.
fn allow_portal(app: &AppHandle, server: &Url) -> tauri::Result<()> {
    let st = state(app);
    let mut grants = st.grants.lock().unwrap_or_else(|e| e.into_inner());
    *grants += 1;
    let capability = CapabilityBuilder::new(format!("portal-{grants}"))
        .remote(format!("{}/*", origin_of(server)))
        .window("main")
        .permission("allow-app-message");
    app.add_capability(capability)
}

fn local_page(app: &AppHandle, url: &Url) -> bool {
    let _ = app;
    matches!(url.scheme(), "tauri") || url.host_str() == Some("tauri.localhost")
}

fn main_window(app: &AppHandle) -> Option<WebviewWindow> {
    app.get_webview_window("main")
}

fn show_main(app: &AppHandle) {
    if let Some(window) = main_window(app) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// Tell the portal something (it listens for "officehub-app" events, see frontend lib/native.ts).
fn tell_page(app: &AppHandle, detail: Value) {
    if let Some(window) = main_window(app) {
        let script = format!(
            "window.dispatchEvent(new CustomEvent('officehub-app', {{ detail: {detail} }}))"
        );
        let _ = window.eval(&script);
    }
}

fn open_main(app: &AppHandle, hidden: bool) -> tauri::Result<()> {
    let server = state(app)
        .settings
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .server
        .clone();
    let server_url = server.as_deref().and_then(|s| Url::parse(s).ok());
    let url = match &server_url {
        Some(url) => {
            allow_portal(app, url)?;
            // Started from the jump list: open right there
            let args: Vec<String> = std::env::args().collect();
            let start = jumplist::path_from_args(&args)
                .and_then(|path| url.join(&path).ok())
                .unwrap_or_else(|| url.clone());
            WebviewUrl::External(start)
        }
        None => WebviewUrl::App("index.html".into()),
    };
    let handle = app.clone();
    let window = WebviewWindowBuilder::new(app, "main", url)
        .title("OfficeHub")
        .inner_size(1280.0, 840.0)
        .min_inner_size(420.0, 560.0)
        .user_agent(USER_AGENT)
        .visible(!hidden)
        .background_throttling(tauri::utils::config::BackgroundThrottlingPolicy::Disabled)
        .on_navigation(move |url| {
            // Within OfficeHub (and the app's own pages) stay here; everything else opens in the browser
            let server = state(&handle)
                .settings
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .server
                .clone();
            let inside = server
                .and_then(|s| Url::parse(&s).ok())
                .is_some_and(|s| origin_of(&s) == origin_of(url));
            let sign_in = state(&handle)
                .sign_in
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .contains(&origin_of(url));
            if inside
                || sign_in
                || local_page(&handle, url)
                || url.scheme() == "about"
                || url.scheme() == "blob"
                || url.scheme() == "data"
            {
                return true;
            }
            let _ = tauri_plugin_opener::open_url(url.as_str(), None::<&str>);
            false
        })
        .build()?;
    #[cfg(windows)]
    {
        // Windows 11 look: Mica behind the title bar, light or dark like the system
        use tauri::window::{Effect, EffectsBuilder};
        let _ = window.set_effects(EffectsBuilder::new().effect(Effect::Mica).build());
    }
    let _ = window;
    Ok(())
}

// ---------- what the portal asks for ----------

#[derive(Deserialize)]
struct Notify {
    title: String,
    body: String,
    link: Option<String>,
}

#[derive(Deserialize)]
struct Ring {
    meeting_id: i64,
    name: String,
    text: String,
    accept: String,
    decline: String,
}

// async: making the ringing window from a synchronous command would block the main thread on Windows
#[tauri::command]
async fn app_message(app: AppHandle, message: Value) {
    match message.get("type").and_then(Value::as_str).unwrap_or("") {
        "notify" => {
            if let Ok(n) = serde_json::from_value::<Notify>(message) {
                notify(&app, &n.title, &n.body, n.link);
            }
        }
        "badge" => {
            let count = message.get("count").and_then(Value::as_i64).unwrap_or(0);
            set_badge(&app, count);
        }
        "ring" => {
            if let Ok(r) = serde_json::from_value::<Ring>(message) {
                ring(&app, r);
            }
        }
        "ring-stop" => stop_ring(&app),
        // Signed in: if this computer has no OfficeHub folder yet, the portal makes an app password for it
        "session" => {
            let signed_in = message.get("signedIn").and_then(Value::as_bool).unwrap_or(false);
            let server = state(&app).settings.lock().unwrap_or_else(|e| e.into_inner()).server.clone();
            if let Some(server) = server.filter(|_| signed_in) {
                if !files::is_set_up(&app, &server) {
                    tell_page(&app, serde_json::json!({ "syncSetup": { "device": std::env::var("COMPUTERNAME").unwrap_or_default() } }));
                }
            }
        }
        // The portal's Files page: where the folder is, how it is doing, and its buttons
        "sync-status" => push_sync_status(&app),
        "sync-open" => files::open_folder(),
        "sync-now" => files::sync_now(),
        "sync-pause" => {
            files::toggle_pause(&app);
            push_sync_status(&app);
        }
        "sync-setup" => {
            let server = state(&app).settings.lock().unwrap_or_else(|e| e.into_inner()).server.clone();
            if server.is_some_and(|s| !files::is_set_up(&app, &s)) {
                tell_page(&app, serde_json::json!({ "syncSetup": { "device": std::env::var("COMPUTERNAME").unwrap_or_default() } }));
            }
        }
        "sync-credentials" => {
            let server = state(&app).settings.lock().unwrap_or_else(|e| e.into_inner()).server.clone();
            let login = message.get("login").and_then(Value::as_str).unwrap_or("");
            let password = message.get("password").and_then(Value::as_str).unwrap_or("");
            if let Some(server) = server.filter(|_| !login.is_empty() && !password.is_empty()) {
                files::set_up(&app, &server, login, password);
            }
        }
        _ => {}
    }
}

fn notify(app: &AppHandle, title: &str, body: &str, link: Option<String>) {
    // Like Teams: the taskbar icon flashes while OfficeHub is in the background
    if let Some(window) = main_window(app) {
        if !window.is_focused().unwrap_or(false) {
            let _ = window.request_user_attention(Some(tauri::UserAttentionType::Informational));
        }
    }
    #[cfg(windows)]
    {
        use tauri_winrt_notification::{Duration, Sound, Toast};
        let handle = app.clone();
        let aumid = app.config().identifier.clone();
        let _ = Toast::new(&aumid)
            .title(title)
            .text1(body)
            .sound(Some(Sound::Default))
            .duration(Duration::Short)
            .on_activated(move |_| {
                show_main(&handle);
                if let Some(link) = &link {
                    tell_page(&handle, serde_json::json!({ "navigate": link }));
                }
                Ok(())
            })
            .show();
    }
    #[cfg(not(windows))]
    {
        use tauri_plugin_notification::NotificationExt;
        let _ = link;
        let _ = app.notification().builder().title(title).body(body).show();
    }
}

fn set_badge(app: &AppHandle, count: i64) {
    if let Some(window) = main_window(app) {
        #[cfg(windows)]
        {
            let icon = if count > 0 {
                Some(badge::image(count))
            } else {
                None
            };
            let _ = window.set_overlay_icon(icon);
        }
        #[cfg(not(windows))]
        {
            let _ = window.set_badge_count(if count > 0 { Some(count) } else { None });
        }
    }
    *state(app).unread.lock().unwrap_or_else(|e| e.into_inner()) = count;
    update_tooltip(app);
}

/// "OfficeHub (3) – Files up to date"
fn update_tooltip(app: &AppHandle) {
    let st = state(app);
    let count = *st.unread.lock().unwrap_or_else(|e| e.into_inner());
    let status = st.sync_status.lock().unwrap_or_else(|e| e.into_inner()).clone();
    let mut tip = if count > 0 { format!("OfficeHub ({count})") } else { "OfficeHub".to_string() };
    if !status.is_empty() {
        tip.push_str(" – ");
        tip.push_str(&status);
    }
    let tray = st.tray.lock().unwrap_or_else(|e| e.into_inner()).clone();
    if let Some(tray) = tray {
        let _ = tray.set_tooltip(Some(tip));
    }
}

/// The sync's status in the tray icon's tooltip (files.rs).
/// Tells the portal (Files page) where the OfficeHub folder is and how the sync is doing.
pub(crate) fn push_sync_status(app: &AppHandle) {
    let server = state(app).settings.lock().unwrap_or_else(|e| e.into_inner()).server.clone();
    let status = files::status_json(app, server.as_deref());
    tell_page(app, serde_json::json!({ "syncStatus": status }));
}

pub(crate) fn set_tray_status(app: &AppHandle, text: &str) {
    *state(app).sync_status.lock().unwrap_or_else(|e| e.into_inner()) = text.to_string();
    update_tooltip(app);
}

fn ring(app: &AppHandle, call: Ring) {
    {
        let st = state(app);
        let mut ringing = st.ringing.lock().unwrap_or_else(|e| e.into_inner());
        if *ringing == Some(call.meeting_id) {
            return;
        }
        *ringing = Some(call.meeting_id);
    }
    // The portal rings itself when it is in front; otherwise a small window like Teams, bottom right
    let in_front = main_window(app)
        .is_some_and(|w| w.is_visible().unwrap_or(false) && w.is_focused().unwrap_or(false));
    if let Some(window) = main_window(app) {
        let _ = window.request_user_attention(Some(tauri::UserAttentionType::Critical));
    }
    if in_front {
        return;
    }
    if let Some(old) = app.get_webview_window("ring") {
        let _ = old.close();
    }
    let mut page = String::from("ring.html?");
    let pairs = [
        ("id", call.meeting_id.to_string()),
        ("name", call.name),
        ("text", call.text),
        ("accept", call.accept),
        ("decline", call.decline),
    ];
    let query: Vec<String> = pairs
        .iter()
        .map(|(k, v)| format!("{k}={}", url_encode(v)))
        .collect();
    page.push_str(&query.join("&"));
    let (width, height) = (380.0, 168.0);
    let mut builder = WebviewWindowBuilder::new(app, "ring", WebviewUrl::App(page.into()))
        .title("OfficeHub")
        .inner_size(width, height)
        .resizable(false)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(true);
    if let Ok(Some(monitor)) = app.primary_monitor() {
        let scale = monitor.scale_factor();
        let size = monitor.size().to_logical::<f64>(scale);
        builder = builder.position(size.width - width - 24.0, size.height - height - 72.0);
    }
    if let Err(error) = builder.build() {
        eprintln!("ringing window: {error}");
    }
}

fn stop_ring(app: &AppHandle) {
    *state(app).ringing.lock().unwrap_or_else(|e| e.into_inner()) = None;
    if let Some(window) = app.get_webview_window("ring") {
        let _ = window.close();
    }
}

fn url_encode(text: &str) -> String {
    let mut out = String::new();
    for byte in text.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(byte as char)
            }
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

/// Accept or decline in the ringing window: the portal does the rest (frontend IncomingCall.vue).
#[tauri::command]
async fn ring_answer(app: AppHandle, action: String) {
    let id = state(&app)
        .ringing
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .take();
    if let Some(window) = app.get_webview_window("ring") {
        let _ = window.close();
    }
    let Some(id) = id else { return };
    if action == "accept" {
        show_main(&app);
    }
    tell_page(
        &app,
        serde_json::json!({ "call": id, "action": if action == "accept" { "accept" } else { "decline" } }),
    );
}

// ---------- the address screen ----------

/// The address screen: check the address, remember it and open the portal.
#[tauri::command]
async fn connect(app: AppHandle, address: String) -> Result<(), String> {
    let url = normalize(&address)?;
    // Without "http://" try https first, then http (many company servers run plain http inside the network)
    let candidates = if address.contains("://") {
        vec![url]
    } else {
        let mut plain = url.clone();
        let _ = plain.set_scheme("http");
        vec![url, plain]
    };
    let url = tauri::async_runtime::spawn_blocking(move || {
        let mut last = Err("unreachable".to_string());
        for candidate in candidates {
            match check_server(&candidate) {
                Ok(config) => return Ok((candidate, config)),
                Err(error) => last = Err(error),
            }
        }
        last
    })
    .await
    .map_err(|_| "unreachable".to_string())??;
    let (url, config) = url;
    remember_sign_in(&app, &config);
    {
        let st = state(&app);
        let mut settings = st.settings.lock().unwrap_or_else(|e| e.into_inner());
        settings.server = Some(url.to_string());
        save_settings(&app, &settings);
    }
    allow_portal(&app, &url).map_err(|e| e.to_string())?;
    if let Some(window) = main_window(&app) {
        window.navigate(url).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Texts for the app's own pages in the system language.
#[tauri::command]
fn ui_texts() -> Value {
    texts::for_system()
}

fn change_server(app: &AppHandle) {
    files::forget(app);
    {
        let st = state(app);
        let mut settings = st.settings.lock().unwrap_or_else(|e| e.into_inner());
        settings.server = None;
        save_settings(app, &settings);
    }
    if let Some(window) = main_window(app) {
        if let Ok(url) = Url::parse("tauri://localhost/index.html") {
            #[cfg(windows)]
            let url = Url::parse("http://tauri.localhost/index.html").unwrap_or(url);
            let _ = window.navigate(url);
        }
    }
    show_main(app);
}

// ---------- tray ----------

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let t = texts::for_system();
    let label = |key: &str| {
        t.get(key)
            .and_then(Value::as_str)
            .unwrap_or(key)
            .to_string()
    };
    let open = MenuItem::with_id(app, "open", label("trayOpen"), true, None::<&str>)?;
    let autostart_on = app.autolaunch().is_enabled().unwrap_or(false);
    let autostart = CheckMenuItem::with_id(
        app,
        "autostart",
        label("trayAutostart"),
        true,
        autostart_on,
        None::<&str>,
    )?;
    // Like Teams: set the status right from the tray
    let statuses = [
        ("auto", "statusAuto"),
        ("available", "statusAvailable"),
        ("busy", "statusBusy"),
        ("dnd", "statusDnd"),
        ("away", "statusAway"),
        ("offline", "statusOffline"),
    ]
    .iter()
    .map(|(id, key)| MenuItem::with_id(app, format!("status:{id}"), label(key), true, None::<&str>))
    .collect::<tauri::Result<Vec<_>>>()?;
    let status_items: Vec<&dyn tauri::menu::IsMenuItem<tauri::Wry>> =
        statuses.iter().map(|i| i as &dyn tauri::menu::IsMenuItem<tauri::Wry>).collect();
    let status = Submenu::with_items(app, label("trayStatus"), true, &status_items)?;
    // The OfficeHub folder in Explorer (like OneDrive)
    let folder = MenuItem::with_id(app, "sync_open", label("syncOpen"), true, None::<&str>)?;
    let pause = CheckMenuItem::with_id(app, "sync_pause", label("syncPauseMenu"), true, files::is_paused(app), None::<&str>)?;
    let server = MenuItem::with_id(app, "server", label("trayServer"), true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", label("trayQuit"), true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &open,
            &status,
            &PredefinedMenuItem::separator(app)?,
            &folder,
            &pause,
            &PredefinedMenuItem::separator(app)?,
            &autostart,
            &server,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;
    let mut builder = TrayIconBuilder::with_id("main")
        .tooltip("OfficeHub")
        .menu(&menu)
        .show_menu_on_left_click(false);
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    let tray = builder
        .on_menu_event(move |app, event| match event.id().as_ref() {
            "open" => show_main(app),
            "autostart" => {
                let launcher = app.autolaunch();
                let on = launcher.is_enabled().unwrap_or(false);
                let _ = if on {
                    launcher.disable()
                } else {
                    launcher.enable()
                };
            }
            "server" => change_server(app),
            "sync_open" => files::open_folder(),
            "sync_pause" => {
                files::toggle_pause(app);
            }
            "quit" => app.exit(0),
            id => {
                if let Some(status) = id.strip_prefix("status:") {
                    tell_page(app, serde_json::json!({ "status": status }));
                }
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main(tray.app_handle());
            }
        })
        .build(app)?;
    *state(app).tray.lock().unwrap_or_else(|e| e.into_inner()) = Some(tray);
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let hidden = std::env::args().any(|a| a == "--hidden");
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            show_main(app);
            // Started again from the jump list: go to that place in the running app
            if let Some(path) = jumplist::path_from_args(&args) {
                tell_page(app, serde_json::json!({ "navigate": path }));
            }
        }))
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_denylist(&["ring"])
                .build(),
        )
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            app_message,
            connect,
            ring_answer,
            ui_texts
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            let settings = load_settings(&handle);
            // Like Teams: starts with Windows (once switched on here, the tray menu switches it off)
            if !settings.autostart_set {
                let _ = handle.autolaunch().enable();
            }
            let first_autostart = !settings.autostart_set;
            *state(&handle)
                .settings
                .lock()
                .unwrap_or_else(|e| e.into_inner()) = Settings {
                autostart_set: true,
                ..settings
            };
            if first_autostart {
                save_settings(
                    &handle,
                    &state(&handle)
                        .settings
                        .lock()
                        .unwrap_or_else(|e| e.into_inner()),
                );
            }
            build_tray(&handle)?;
            #[cfg(windows)]
            {
                let _ = jumplist::install(&jumplist::tasks(&texts::for_system()));
            }
            refresh_sign_in(&handle);
            open_main(&handle, hidden)?;
            if let Some(server) = state(&handle).settings.lock().unwrap_or_else(|e| e.into_inner()).server.clone() {
                files::start(&handle, &server);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the window keeps OfficeHub running in the notification area (like Teams)
            if window.label() == "main" {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                    let app = window.app_handle();
                    let first = {
                        let st = state(app);
                        let mut settings = st.settings.lock().unwrap_or_else(|e| e.into_inner());
                        let first = !settings.tray_hint_shown;
                        settings.tray_hint_shown = true;
                        if first {
                            save_settings(app, &settings);
                        }
                        first
                    };
                    if first {
                        let t = texts::for_system();
                        let get = |key: &str| {
                            t.get(key).and_then(Value::as_str).unwrap_or("").to_string()
                        };
                        notify(app, &get("hiddenTitle"), &get("hiddenBody"), None);
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .unwrap_or_else(|e| eprintln!("OfficeHub could not start: {e}"));
}
