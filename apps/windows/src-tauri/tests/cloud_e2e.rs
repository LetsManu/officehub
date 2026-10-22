//! Windows only: the OfficeHub folder as a real cloud folder (Cloud Files API) against a real OfficeHub server.
//! Checks that server files arrive as placeholders without content, that opening one downloads it, that
//! "Free up space" works, and that a new local file is uploaded and becomes a placeholder in sync.
//!
//! Runs only when a server is given (apps/windows/sync-e2e-windows.ps1 starts a demo server and does that):
//!   OFFICEHUB_SYNC_SERVER, OFFICEHUB_SYNC_LOGIN, OFFICEHUB_SYNC_PASSWORD, OFFICEHUB_SYNC_SPACE, OFFICEHUB_SYNC_SPACE_ID
#![cfg(windows)]

use cloud_filter::placeholder::Placeholder;
use officehub_app::sync::api::Api;
use officehub_app::sync::cloud::{self, CloudStore};
use officehub_app::sync::engine::{Engine, Words};
use officehub_app::sync::state::State;

fn env(name: &str) -> Option<String> {
    std::env::var(name).ok().filter(|v| !v.is_empty())
}

#[test]
fn placeholders_download_on_open_and_uploads_work() {
    let (Some(server), Some(login), Some(password), Some(space), Some(space_id)) = (
        env("OFFICEHUB_SYNC_SERVER"),
        env("OFFICEHUB_SYNC_LOGIN"),
        env("OFFICEHUB_SYNC_PASSWORD"),
        env("OFFICEHUB_SYNC_SPACE"),
        env("OFFICEHUB_SYNC_SPACE_ID").and_then(|s| s.parse::<i64>().ok()),
    ) else {
        eprintln!("no OFFICEHUB_SYNC_SERVER: skipped");
        return;
    };
    let api = Api::new(&server, &login, &password);
    let root = std::env::temp_dir().join(format!("OfficeHubTest-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);

    // A file that is only on the server so far
    let content = "Hallo aus OfficeHub ".repeat(5000); // ~100 KB: several 4 KiB blocks
    api.create_file(space_id, None, "Willkommen.txt", content.as_bytes()).expect("upload");

    eprintln!("step: connect");
    let connection = cloud::connect(&root, &login, "OfficeHub Test", api.clone()).expect("register and connect");
    let store = CloudStore { root: root.clone() };
    let mut engine = Engine::new(api.clone(), store, State::default(), "CI".into(), Words { conflict: "conflict".into() });
    loop {
        let changes = api.changes(engine.state.cursor, 0, None).expect("changes");
        if !engine.apply(changes) {
            break;
        }
    }

    eprintln!("step: placeholder check");
    // A placeholder: the right size, nothing downloaded yet
    let file = root.join(&space).join("Willkommen.txt");
    let meta = std::fs::metadata(&file).expect("placeholder exists");
    assert_eq!(meta.len(), content.len() as u64);
    let info = Placeholder::open(&file).expect("open").info().expect("info").expect("is a placeholder");
    assert_eq!(info.on_disk_data_size(), 0, "nothing downloaded before opening");
    assert!(info.is_in_sync());

    eprintln!("step: hydrate");
    // Opening it downloads it (fetch_data)
    assert_eq!(std::fs::read_to_string(&file).expect("read hydrates"), content);
    let info = Placeholder::open(&file).unwrap().info().unwrap().unwrap();
    assert_eq!(info.on_disk_data_size(), content.len() as i64);

    eprintln!("step: free up space");
    // "Free up space": the content goes again, the file stays
    cloud::free_up_space(&file).expect("free up space");
    assert_eq!(Placeholder::open(&file).unwrap().info().unwrap().unwrap().on_disk_data_size(), 0);
    assert_eq!(std::fs::read_to_string(&file).unwrap(), content);

    eprintln!("step: upload");
    // A new local file is uploaded and becomes a placeholder in sync
    let new_file = root.join(&space).join("Neu.txt");
    std::fs::write(&new_file, "von Windows").unwrap();
    engine.scan();
    let info = Placeholder::open(&new_file).unwrap().info().unwrap().expect("converted to a placeholder");
    assert!(info.is_in_sync());
    let id = engine.state.files.iter().find(|(_, e)| e.local_name == "Neu.txt").map(|(id, _)| *id).expect("known");
    let (_, data) = api.download_current(id).expect("on the server");
    assert_eq!(data, b"von Windows");

    eprintln!("step: server change");
    // A change on the server replaces the local placeholder's content
    let welcome = engine.state.files.iter().find(|(_, e)| e.local_name == "Willkommen.txt").map(|(id, e)| (*id, e.version)).unwrap();
    api.save(welcome.0, welcome.1, b"neu vom Server").expect("save on server");
    let changes = api.changes(engine.state.cursor, 0, None).unwrap();
    engine.apply(changes);
    assert_eq!(std::fs::read_to_string(&file).unwrap(), "neu vom Server");

    drop(connection);
    cloud::unregister(&login).expect("unregister");
    let _ = std::fs::remove_dir_all(&root);
}
