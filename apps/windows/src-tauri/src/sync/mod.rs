//! The "OfficeHub" folder on this computer, kept in sync with the person's spaces, like OneDrive.
//!
//! Two background threads share one `Engine`:
//! - the server thread asks /api/sync/changes (long polling) and applies what changed;
//! - the local thread waits for changes in the folder (file system watcher, a little delay so a save is finished,
//!   and every few minutes anyway) and scans.
//! Sign-in is an app password the portal creates for this computer (frontend lib/native.ts → "sync-credentials").

pub mod api;
#[cfg(windows)]
pub mod cloud;
pub mod engine;
pub mod names;
pub mod state;
pub mod store;

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use api::{Api, ApiError};
use engine::{Engine, Event, Words};
use state::State;

#[cfg(windows)]
type PlatformStore = cloud::CloudStore;
#[cfg(not(windows))]
type PlatformStore = store::FullStore;

pub struct Config {
    pub server: String,
    pub login: String,
    pub password: String,
    /// The sync folder, e.g. C:\Users\anna\OfficeHub
    pub root: PathBuf,
    /// Where the engine remembers what is in sync
    pub state_file: PathBuf,
    pub device: String,
    pub display_name: String,
    pub words: Words,
}

/// Status for the tray icon.
#[derive(Clone, Debug, PartialEq)]
pub enum Status {
    Syncing,
    UpToDate,
    Offline,
    SignInNeeded,
    Paused,
}

pub type Report = Arc<dyn Fn(Option<Status>, Option<Event>) + Send + Sync>;

/// Why the last talk with the server failed (shown under "Files" in the app), None while it works.
pub static LAST_ERROR: Mutex<Option<String>> = Mutex::new(None);

fn note_error(error: Option<String>) {
    *LAST_ERROR.lock().unwrap_or_else(|e| e.into_inner()) = error;
}

/// A running sync; stops when dropped.
pub struct Running {
    stop: Arc<AtomicBool>,
    paused: Arc<AtomicBool>,
    wake: Sender<()>,
    pub root: PathBuf,
    // Kept alive while syncing: the folder watcher, and on Windows the Cloud Files connection
    _keep: Vec<Box<dyn std::any::Any + Send>>,
}

impl Running {
    pub fn pause(&self, paused: bool) {
        self.paused.store(paused, Ordering::SeqCst);
        let _ = self.wake.send(());
    }

    /// Compare the folder now (the portal's "Sync now").
    pub fn now(&self) {
        let _ = self.wake.send(());
    }

    pub fn is_paused(&self) -> bool {
        self.paused.load(Ordering::SeqCst)
    }
}

impl Drop for Running {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        let _ = self.wake.send(());
    }
}

const LONG_POLL: u32 = 25;
const SCAN_EVERY: Duration = Duration::from_secs(300);
const SETTLE: Duration = Duration::from_millis(1500);

fn save(engine: &Engine<PlatformStore>, file: &std::path::Path) {
    let _ = engine.state.save(file);
}

pub fn start(config: Config, report: Report) -> std::io::Result<Running> {
    std::fs::create_dir_all(&config.root)?;
    let api = Api::new(&config.server, &config.login, &config.password);
    let mut state = State::load(&config.state_file).unwrap_or_default();
    if state.server != config.server || !state.login.eq_ignore_ascii_case(&config.login) {
        // Another portal or person: start over (the files already here are kept and compared)
        state = State { server: config.server.clone(), login: config.login.clone(), ..State::default() };
    }

    let mut keep: Vec<Box<dyn std::any::Any + Send>> = Vec::new();
    #[cfg(windows)]
    let store = {
        let connection = cloud::connect(&config.root, &config.login, &config.display_name, api.clone())?;
        keep.push(Box::new(connection));
        cloud::CloudStore { root: config.root.clone() }
    };
    #[cfg(not(windows))]
    let store = store::FullStore { root: config.root.clone(), api: api.clone() };

    let engine = Arc::new(Mutex::new(Engine::new(api.clone(), store, state, config.device.clone(), config.words.clone())));
    let stop = Arc::new(AtomicBool::new(false));
    let paused = Arc::new(AtomicBool::new(false));
    let (wake, woken) = channel::<()>();
    // Set once the first server sync is done: local changes are only compared after that
    let ready = Arc::new(AtomicBool::new(false));

    // Folder watcher → local thread
    let watch_tx = wake.clone();
    let watcher = notify::recommended_watcher(move |result: notify::Result<notify::Event>| {
        if result.is_ok() {
            let _ = watch_tx.send(());
        }
    });
    if let Ok(mut watcher) = watcher {
        use notify::Watcher;
        if watcher.watch(&config.root, notify::RecursiveMode::Recursive).is_ok() {
            keep.push(Box::new(watcher));
        }
    }

    let tell = |report: &Report, engine: &mut Engine<PlatformStore>| {
        for event in engine.take_events() {
            report(None, Some(event));
        }
    };

    // Server → this computer
    {
        let (engine, stop, paused, ready, report) = (engine.clone(), stop.clone(), paused.clone(), ready.clone(), report.clone());
        let (state_file, api) = (config.state_file.clone(), api.clone());
        std::thread::Builder::new().name("officehub-sync-server".into()).spawn(move || {
            let mut backoff = 5u64;
            while !stop.load(Ordering::SeqCst) {
                if paused.load(Ordering::SeqCst) {
                    report(Some(Status::Paused), None);
                    std::thread::sleep(Duration::from_secs(2));
                    continue;
                }
                let cursor = engine.lock().map(|e| e.state.cursor).unwrap_or(0);
                let first = cursor == 0 || !ready.load(Ordering::SeqCst);
                if first {
                    report(Some(Status::Syncing), None);
                }
                match api.changes(cursor, if first { 0 } else { LONG_POLL }, None) {
                    Ok(changes) => {
                        backoff = 5;
                        note_error(None);
                        let busy = !changes.items.is_empty() || !changes.removed.is_empty();
                        if busy {
                            report(Some(Status::Syncing), None);
                        }
                        let more = match engine.lock() {
                            Ok(mut e) => {
                                let more = e.apply(changes);
                                save(&e, &state_file);
                                tell(&report, &mut e);
                                more
                            }
                            Err(_) => false,
                        };
                        if !more {
                            if !ready.swap(true, Ordering::SeqCst) {
                                // First time in sync: now compare the folder
                                let _ = wake_local(&engine, &report, &state_file);
                            }
                            report(Some(Status::UpToDate), None);
                        }
                    }
                    Err(ApiError::Status(401, code)) => {
                        note_error(Some(format!("401 {code}")));
                        report(Some(Status::SignInNeeded), None);
                        sleep_unless(&stop, Duration::from_secs(60));
                    }
                    Err(e) => {
                        note_error(Some(match &e {
                            ApiError::Status(status, code) => format!("{status} {code}"),
                            ApiError::Offline(message) => message.clone(),
                        }));
                        report(Some(Status::Offline), None);
                        sleep_unless(&stop, Duration::from_secs(backoff));
                        backoff = (backoff * 2).min(120);
                    }
                }
            }
        })?;
    }

    // This computer → server
    {
        let (engine, stop, paused, ready, report) = (engine.clone(), stop.clone(), paused.clone(), ready.clone(), report.clone());
        let state_file = config.state_file.clone();
        std::thread::Builder::new().name("officehub-sync-local".into()).spawn(move || {
            while !stop.load(Ordering::SeqCst) {
                match woken.recv_timeout(SCAN_EVERY) {
                    Ok(()) => {
                        // Let the save finish: wait until nothing happened for a moment
                        while woken.recv_timeout(SETTLE).is_ok() {}
                    }
                    Err(RecvTimeoutError::Timeout) => {}
                    Err(RecvTimeoutError::Disconnected) => break,
                }
                if stop.load(Ordering::SeqCst) {
                    break;
                }
                if paused.load(Ordering::SeqCst) || !ready.load(Ordering::SeqCst) {
                    continue;
                }
                let _ = wake_local(&engine, &report, &state_file);
            }
        })?;
    }

    Ok(Running { stop, paused, wake, root: config.root, _keep: keep })
}

fn wake_local(engine: &Arc<Mutex<Engine<PlatformStore>>>, report: &Report, state_file: &std::path::Path) -> Option<()> {
    let (api, status) = {
        let mut e = engine.lock().ok()?;
        e.scan();
        save(&e, state_file);
        for event in e.take_events() {
            report(None, Some(event));
        }
        (e.api.clone(), round_report(&e))
    };
    send_report(api, status);
    Some(())
}

const REPORT_FAILED_KEPT: usize = 20;
const REPORT_EVERY: Duration = Duration::from_secs(600);

/// How this sync round went, for the portal (POST /api/sync/report).
fn round_report(e: &Engine<PlatformStore>) -> serde_json::Value {
    let error = LAST_ERROR.lock().unwrap_or_else(|e| e.into_inner()).clone();
    let failed: Vec<serde_json::Value> = e
        .failed
        .iter()
        .take(REPORT_FAILED_KEPT)
        .map(|(path, reason)| serde_json::json!({ "path": path, "reason": reason }))
        .collect();
    serde_json::json!({
        "device_name": e.device.chars().take(80).collect::<String>(),
        "ok": error.is_none(),
        "failed": failed,
        "failed_count": e.failed.len(),
        "pending_uploads": e.waiting,
        "error": error.unwrap_or_default().chars().take(200).collect::<String>(),
    })
}

/// What was sent last and when: the same news goes out again only now and then.
static LAST_REPORT: Mutex<Option<(serde_json::Value, std::time::Instant)>> = Mutex::new(None);
static REPORTING: AtomicBool = AtomicBool::new(false);

/// Sends the report on its own thread, so a slow or failed report never holds up syncing.
fn send_report(api: Api, status: serde_json::Value) {
    {
        let last = LAST_REPORT.lock().unwrap_or_else(|e| e.into_inner());
        if let Some((sent, at)) = last.as_ref() {
            if *sent == status && at.elapsed() < REPORT_EVERY {
                return;
            }
        }
    }
    if REPORTING.swap(true, Ordering::SeqCst) {
        return; // one report at a time; the next round sends the news
    }
    let started = std::thread::Builder::new().name("officehub-sync-report".into()).spawn(move || {
        // A portal without the report endpoint (older version) answers 404: nothing to do, syncing goes on
        if matches!(api.report(&status), Ok(()) | Err(ApiError::Status(404, _))) {
            *LAST_REPORT.lock().unwrap_or_else(|e| e.into_inner()) = Some((status, std::time::Instant::now()));
        }
        REPORTING.store(false, Ordering::SeqCst);
    });
    if started.is_err() {
        REPORTING.store(false, Ordering::SeqCst);
    }
}

fn sleep_unless(stop: &AtomicBool, total: Duration) {
    let step = Duration::from_millis(500);
    let mut waited = Duration::ZERO;
    while waited < total && !stop.load(Ordering::SeqCst) {
        std::thread::sleep(step);
        waited += step;
    }
}
