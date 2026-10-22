fn main() {
    // The app's own commands, each with its own permission: the company's portal only gets `app_message`
    // (capability added at run time for its address), the app's own pages the rest (capabilities/local.json).
    let manifest = tauri_build::AppManifest::new().commands(&["app_message", "connect", "ring_answer", "ui_texts"]);
    if let Err(error) = tauri_build::try_build(tauri_build::Attributes::new().app_manifest(manifest)) {
        panic!("{error:#}");
    }
}
