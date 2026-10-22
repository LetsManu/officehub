//! Two computers syncing the same space through a real OfficeHub server (full files, no placeholders).
//!
//! Runs only when a server is given:
//!   OFFICEHUB_SYNC_SERVER=http://127.0.0.1:8011 OFFICEHUB_SYNC_LOGIN=anna@… OFFICEHUB_SYNC_PASSWORD=<app password>
//!   OFFICEHUB_SYNC_SPACE=<space name> cargo test --test sync_e2e
//! (apps/windows/sync-e2e.sh starts a demo server and does that.)

use std::path::{Path, PathBuf};

use officehub_app::sync::api::Api;
use officehub_app::sync::engine::{Engine, Event, Words};
use officehub_app::sync::state::State;
use officehub_app::sync::store::FullStore;

struct Computer {
    engine: Engine<FullStore>,
    root: PathBuf,
}

impl Computer {
    fn new(name: &str, api: &Api) -> Computer {
        let root = std::env::temp_dir().join(format!("officehub-sync-e2e-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        let store = FullStore { root: root.clone(), api: api.clone() };
        let words = Words { conflict: "Konflikt".into() };
        Computer { engine: Engine::new(api.clone(), store, State::default(), name.into(), words), root }
    }

    /// Everything the server has new for us.
    fn pull(&mut self) {
        loop {
            let changes = self.engine.api.changes(self.engine.state.cursor, 0, None).unwrap();
            if !self.engine.apply(changes) {
                break;
            }
        }
    }

    fn push(&mut self) {
        self.engine.scan();
    }

    fn path(&self, space: &str, rel: &str) -> PathBuf {
        self.root.join(space).join(rel)
    }

    fn write(&self, space: &str, rel: &str, text: &str) {
        let path = self.path(space, rel);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, text).unwrap();
        // A different modification time even within the same second on coarse file systems
        std::thread::sleep(std::time::Duration::from_millis(20));
    }

    fn read(&self, space: &str, rel: &str) -> Option<String> {
        std::fs::read_to_string(self.path(space, rel)).ok()
    }

    fn names(&self, space: &str, dir: &str) -> Vec<String> {
        let mut names: Vec<String> = std::fs::read_dir(self.root.join(space).join(dir))
            .map(|items| items.flatten().map(|i| i.file_name().to_string_lossy().to_string()).collect())
            .unwrap_or_default();
        names.sort();
        names
    }
}

fn env(name: &str) -> Option<String> {
    std::env::var(name).ok().filter(|v| !v.is_empty())
}

#[test]
fn two_computers_stay_in_sync() {
    let (Some(server), Some(login), Some(password), Some(space)) = (
        env("OFFICEHUB_SYNC_SERVER"),
        env("OFFICEHUB_SYNC_LOGIN"),
        env("OFFICEHUB_SYNC_PASSWORD"),
        env("OFFICEHUB_SYNC_SPACE"),
    ) else {
        eprintln!("no OFFICEHUB_SYNC_SERVER: skipped");
        return;
    };
    let api = Api::new(&server, &login, &password);
    eprintln!("syncing against {server}");
    let mut a = Computer::new("PC-A", &api);
    let mut b = Computer::new("PC-B", &api);
    let s = space.as_str();

    // First sync: the space folder appears
    a.pull();
    assert!(a.root.join(s).is_dir(), "space folder on A");

    // A new file on A reaches B
    a.write(s, "Notiz.txt", "eins");
    a.push();
    b.pull();
    assert_eq!(b.read(s, "Notiz.txt").as_deref(), Some("eins"));

    // B changes it, A gets the new version
    b.write(s, "Notiz.txt", "zwei");
    b.push();
    a.pull();
    assert_eq!(a.read(s, "Notiz.txt").as_deref(), Some("zwei"));

    // Both change it: B's version wins the race, A keeps its own as a conflict copy, nothing is lost
    a.write(s, "Notiz.txt", "von A");
    b.write(s, "Notiz.txt", "von B");
    b.push();
    a.push();
    let events = a.engine.take_events();
    assert!(events.iter().any(|e| matches!(e, Event::Conflict { .. })), "conflict reported: {events:?}");
    assert_eq!(a.read(s, "Notiz.txt").as_deref(), Some("von B"));
    let copy = a.names(s, "").into_iter().find(|n| n.contains("Konflikt")).expect("conflict copy on A");
    assert_eq!(a.read(s, &copy).as_deref(), Some("von A"));
    a.push(); // the copy is uploaded as its own file
    b.pull();
    assert_eq!(b.read(s, &copy).as_deref(), Some("von A"));

    // Rename on A → renamed on B
    std::fs::rename(a.path(s, "Notiz.txt"), a.path(s, "Protokoll.txt")).unwrap();
    a.push();
    b.pull();
    assert_eq!(b.read(s, "Protokoll.txt").as_deref(), Some("von B"));
    assert!(!b.path(s, "Notiz.txt").exists());

    // New folder on A, file moved into it
    std::fs::create_dir_all(a.path(s, "Ordner")).unwrap();
    std::fs::rename(a.path(s, "Protokoll.txt"), a.path(s, "Ordner/Protokoll.txt")).unwrap();
    a.push();
    b.pull();
    assert_eq!(b.read(s, "Ordner/Protokoll.txt").as_deref(), Some("von B"));

    // Folder renamed on A → on B too, with its content
    std::fs::rename(a.path(s, "Ordner"), a.path(s, "Archiv")).unwrap();
    a.push();
    b.pull();
    assert_eq!(b.read(s, "Archiv/Protokoll.txt").as_deref(), Some("von B"));
    assert!(!b.path(s, "Ordner").exists());

    // Deleted on B → gone on A (it is in the space's trash on the server)
    std::fs::remove_file(b.path(s, "Archiv/Protokoll.txt")).unwrap();
    b.push();
    a.pull();
    assert!(!a.path(s, "Archiv/Protokoll.txt").exists());

    // Helper files of programs stay local
    a.write(s, "~$Bericht.docx", "lock");
    a.push();
    b.pull();
    assert!(!b.path(s, "~$Bericht.docx").exists());

    // A file type spaces do not take stays on A and is reported once
    a.write(s, "tool.exe", "MZ");
    a.push();
    a.push();
    let events = a.engine.take_events();
    assert_eq!(events.iter().filter(|e| matches!(e, Event::NotSupported { .. })).count(), 1, "{events:?}");

    // State survives a restart
    let file = a.root.join("..").join(format!("officehub-sync-e2e-state-{}.json", std::process::id()));
    a.engine.state.save(&file).unwrap();
    let loaded = State::load(&file).unwrap();
    assert_eq!(loaded.cursor, a.engine.state.cursor);
    assert_eq!(loaded.files.len(), a.engine.state.files.len());
    let _ = std::fs::remove_file(&file);

    for dir in [&a.root, &b.root] {
        let _ = std::fs::remove_dir_all(dir);
    }
    let _ = Path::new("");
}
