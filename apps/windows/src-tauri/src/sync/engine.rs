//! Brings both sides together, like OneDrive:
//! - `apply`: what changed on the server (from /api/sync/changes) is done in the sync folder;
//! - `scan`: what changed in the sync folder (new, changed, renamed, moved, deleted) is sent to the server.
//!
//! A file both sides changed is never lost: the local version is kept next to it as
//! "Name (Konflikt PC 2026-10-22).ext" and uploaded as its own file. Deleting many files at once locally is not
//! passed on (they come back), so a mistake in Explorer cannot empty a space.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use super::api::{Api, ApiError, Changes, Item};
use super::names;
use super::state::{key, Entry, Kind, SpaceEntry, State};
use super::store::{mtime, Store};

/// Something the person should hear about (the app shows it as a notification).
#[derive(Debug, Clone, PartialEq)]
pub enum Event {
    /// Both sides changed a file; the local version was kept under `copy`.
    Conflict { name: String, copy: String },
    /// The file type is not allowed in spaces (or the file is too large): it stays only on this computer.
    NotSupported { name: String },
    /// Someone has it checked out or is editing it: the change waits.
    Busy { name: String },
    /// Many files disappeared at once locally; they were restored instead of deleted on the server.
    ManyDeletes { count: usize },
    /// Folders right in the sync folder are spaces; new ones are made in the portal.
    NewSpaceFolder { name: String },
}

/// Words for conflict copies (the person's language).
#[derive(Clone)]
pub struct Words {
    pub conflict: String,
}

pub struct Engine<S: Store> {
    pub api: Api,
    pub store: S,
    pub state: State,
    pub device: String,
    pub words: Words,
    /// Notified once per file and state, not at every scan
    told: HashSet<String>,
    events: Vec<Event>,
}

/// A local deletion of more than this many items, and more than a third of all, needs the portal.
const MASS_DELETE: usize = 10;

impl<S: Store> Engine<S> {
    pub fn new(api: Api, store: S, state: State, device: String, words: Words) -> Self {
        Engine { api, store, state, device, words, told: HashSet::new(), events: Vec::new() }
    }

    /// Events since the last call.
    pub fn take_events(&mut self) -> Vec<Event> {
        std::mem::take(&mut self.events)
    }

    fn tell(&mut self, once: String, event: Event) {
        if self.told.insert(once) {
            self.events.push(event);
        }
    }

    fn today() -> String {
        // yyyy-mm-dd from the system clock (UTC is fine for a file name)
        let days = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() / 86_400)
            .unwrap_or(0) as i64;
        let (y, m, d) = civil(days);
        format!("{y:04}-{m:02}-{d:02}")
    }

    fn conflict_name(&self, rel: &Path) -> PathBuf {
        let name = rel.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
        let copy = names::conflict_copy(&name, &self.words.conflict, &self.device, &Self::today());
        let dir = rel.parent().map(Path::to_path_buf).unwrap_or_default();
        let unique = names::unique(&copy, |c| self.store.abs(&dir.join(c)).exists());
        dir.join(unique)
    }

    fn dirty(&self, rel: &Path, entry: &Entry) -> bool {
        let path = self.store.abs(rel);
        match std::fs::metadata(&path) {
            Ok(meta) if meta.is_file() => match self.store.changed(rel, entry) {
                Some(changed) => changed,
                None => meta.len() != entry.size || mtime(&path) != Some(entry.mtime),
            },
            _ => false,
        }
    }

    // ---------- server → this computer ----------

    /// Does what the server reports. Returns true when there may be more (ask again right away).
    pub fn apply(&mut self, changes: Changes) -> bool {
        self.apply_spaces(&changes);
        for removed in &changes.removed {
            match removed.kind.as_str() {
                "file" => self.remove_local(Kind::File, removed.id),
                "folder" => self.remove_local(Kind::Folder, removed.id),
                _ => {}
            }
        }
        if changes.reset {
            // A whole tree: whatever we knew and the server no longer lists is gone
            let listed: HashSet<(Kind, i64)> = changes
                .items
                .iter()
                .map(|i| (if i.is_folder() { Kind::Folder } else { Kind::File }, i.id))
                .collect();
            for kind in [Kind::File, Kind::Folder] {
                let gone: Vec<i64> =
                    self.state.entries(kind).keys().filter(|id| !listed.contains(&(kind, **id))).copied().collect();
                for id in gone {
                    self.remove_local(kind, id);
                }
            }
        }
        let mut queue: Vec<Item> = changes.items;
        // Parents first; whatever still waits for a parent is tried again after the others
        for _ in 0..8 {
            let before = queue.len();
            queue.retain(|item| !self.apply_item(item));
            if queue.is_empty() || queue.len() == before {
                break;
            }
        }
        self.state.cursor = changes.cursor;
        changes.more
    }

    fn apply_spaces(&mut self, changes: &Changes) {
        let listed: HashSet<i64> = changes.spaces.iter().map(|s| s.id).collect();
        for space in &changes.spaces {
            match self.state.spaces.get(&space.id).cloned() {
                Some(known) => {
                    if known.name != space.name {
                        let dir = self.state.free_space_dir(space.id, &space.name);
                        let _ = std::fs::rename(self.store.abs(Path::new(&known.dir)), self.store.abs(Path::new(&dir)));
                        self.state.spaces.insert(
                            space.id,
                            SpaceEntry { name: space.name.clone(), dir, writable: space.writable },
                        );
                    } else if known.writable != space.writable {
                        if let Some(s) = self.state.spaces.get_mut(&space.id) {
                            s.writable = space.writable;
                        }
                    }
                }
                None => {
                    let dir = self.state.free_space_dir(space.id, &space.name);
                    if self.store.make_dir(Path::new(&dir)).is_ok() {
                        self.state.spaces.insert(
                            space.id,
                            SpaceEntry { name: space.name.clone(), dir, writable: space.writable },
                        );
                    }
                }
            }
        }
        let gone: Vec<i64> = self.state.spaces.keys().filter(|id| !listed.contains(id)).copied().collect();
        for id in gone {
            self.remove_space(id);
        }
    }

    /// No longer a member: the space folder goes; files changed here and not uploaded yet stay in a renamed folder.
    fn remove_space(&mut self, space_id: i64) {
        let Some(space) = self.state.spaces.get(&space_id).cloned() else { return };
        let dir = self.store.abs(Path::new(&space.dir));
        let unsaved = self.state.files.iter().any(|(id, e)| {
            e.space_id == space_id && self.state.path(Kind::File, *id).is_some_and(|rel| self.dirty(&rel, e))
        });
        if unsaved {
            let keep = names::unique(&format!("{} ({})", space.dir, self.words.conflict), |c| {
                self.store.abs(Path::new(c)).exists()
            });
            let _ = std::fs::rename(&dir, self.store.abs(Path::new(&keep)));
        } else {
            let _ = remove_all(&dir);
        }
        self.state.forget_space(space_id);
    }

    /// The local file or folder goes (deleted on the server or moved to its trash).
    fn remove_local(&mut self, kind: Kind, id: i64) {
        let Some(rel) = self.state.path(kind, id) else {
            self.state.entries_mut(kind).remove(&id);
            return;
        };
        let path = self.store.abs(&rel);
        match kind {
            Kind::File => {
                let entry = self.state.files.get(&id).cloned();
                if entry.is_some_and(|e| self.dirty(&rel, &e)) {
                    // Changed here meanwhile: keep it as a new file instead of losing the change
                    let copy = self.conflict_name(&rel);
                    let _ = std::fs::rename(&path, self.store.abs(&copy));
                } else {
                    self.store.set_read_only(&rel, false);
                    let _ = std::fs::remove_file(&path);
                }
                self.state.files.remove(&id);
            }
            Kind::Folder => {
                let _ = remove_all(&path);
                for (k, i) in self.state.subtree(id) {
                    self.state.entries_mut(k).remove(&i);
                }
            }
        }
    }

    /// Returns false while the item's folder is not known yet.
    fn apply_item(&mut self, item: &Item) -> bool {
        let kind = if item.is_folder() { Kind::Folder } else { Kind::File };
        if item.deleted {
            if self.state.entries(kind).contains_key(&item.id) {
                self.remove_local(kind, item.id);
            }
            return true;
        }
        if !self.state.spaces.contains_key(&item.space_id) {
            return true; // not (or no longer) one of my spaces
        }
        let Some(parent_dir) = self.state.dir_path(item.space_id, item.parent_id) else {
            return false;
        };
        let known = self.state.entries(kind).get(&item.id).cloned();
        match known {
            None => self.add_item(kind, item, &parent_dir),
            Some(entry) => self.update_item(kind, item, entry),
        }
        true
    }

    fn add_item(&mut self, kind: Kind, item: &Item, parent_dir: &Path) {
        let local_name = self.state.free_name(item.space_id, item.parent_id, &item.name, None);
        let rel = parent_dir.join(&local_name);
        let mut entry = Entry {
            space_id: item.space_id,
            parent_id: item.parent_id,
            name: item.name.clone(),
            local_name,
            version: item.version,
            size: item.size,
            mtime: 0,
            read_only: item.read_only,
            hash: 0,
        };
        let path = self.store.abs(&rel);
        match kind {
            Kind::Folder => {
                if self.store.make_dir(&rel).is_err() {
                    return;
                }
            }
            Kind::File => {
                if path.exists() {
                    // A file of the same name is already here (first sync on this computer, or the sync was reset):
                    // keep it under another name so nothing is overwritten; it is uploaded as its own file
                    let copy = self.conflict_name(&rel);
                    if std::fs::rename(&path, self.store.abs(&copy)).is_err() {
                        return;
                    }
                }
                match self.store.put_file(&rel, item) {
                    Ok(t) => {
                        entry.mtime = t;
                        entry.hash = self.store.fingerprint(&rel);
                    }
                    Err(_) => return,
                }
                if item.read_only {
                    self.store.set_read_only(&rel, true);
                }
            }
        }
        self.state.entries_mut(kind).insert(item.id, entry);
    }

    fn update_item(&mut self, kind: Kind, item: &Item, entry: Entry) {
        let old_rel = self.state.path(kind, item.id);
        let moved = entry.parent_id != item.parent_id || entry.name != item.name || entry.space_id != item.space_id;
        if moved {
            let local_name = self.state.free_name(item.space_id, item.parent_id, &item.name, Some((kind, item.id)));
            if let Some(e) = self.state.entries_mut(kind).get_mut(&item.id) {
                e.space_id = item.space_id;
                e.parent_id = item.parent_id;
                e.name = item.name.clone();
                e.local_name = local_name;
            }
        }
        let Some(rel) = self.state.path(kind, item.id) else { return };
        if let Some(old) = old_rel.filter(|old| *old != rel) {
            if self.store.abs(&old).exists() {
                let _ = std::fs::rename(self.store.abs(&old), self.store.abs(&rel));
            }
        }
        if kind == Kind::Folder {
            if !self.store.abs(&rel).exists() {
                let _ = self.store.make_dir(&rel);
            }
            return;
        }
        let path = self.store.abs(&rel);
        let mut current = self.state.files.get(&item.id).cloned().unwrap_or(entry);
        if item.version != current.version || !path.exists() {
            if path.exists() && self.dirty(&rel, &current) {
                let copy = self.conflict_name(&rel);
                if std::fs::rename(&path, self.store.abs(&copy)).is_ok() {
                    self.tell(
                        format!("conflict:{}:{}", item.id, item.version),
                        Event::Conflict {
                            name: item.name.clone(),
                            copy: copy.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default(),
                        },
                    );
                }
            }
            let written = if path.exists() {
                self.store.replace_file(&rel, item)
            } else {
                self.store.put_file(&rel, item)
            };
            if let Ok(t) = written {
                current.version = item.version;
                current.size = item.size;
                current.mtime = t;
                current.hash = self.store.fingerprint(&rel);
            }
        }
        if current.read_only != item.read_only {
            self.store.set_read_only(&rel, item.read_only);
            current.read_only = item.read_only;
        }
        self.state.files.insert(item.id, current);
    }

    // ---------- this computer → server ----------

    /// Compares the sync folder with what was last in sync and sends the differences to the server.
    pub fn scan(&mut self) {
        // Folder renames first (they change the paths of everything inside), then the rest
        for _ in 0..4 {
            if !self.scan_once() {
                break;
            }
        }
    }

    /// Returns true when folders were renamed or moved (scan again with the new paths).
    fn scan_once(&mut self) -> bool {
        let root = self.store.root().to_path_buf();
        if !root.is_dir() {
            return false;
        }
        let index = self.state.index();
        let space_dirs: HashMap<String, i64> =
            self.state.spaces.iter().map(|(id, s)| (s.dir.to_lowercase(), *id)).collect();
        let mut seen: HashSet<String> = HashSet::new();
        let mut new_dirs: Vec<PathBuf> = Vec::new();
        let mut new_files: Vec<PathBuf> = Vec::new();
        let mut changed: Vec<i64> = Vec::new();

        let Ok(top) = std::fs::read_dir(&root) else { return false };
        for item in top.flatten() {
            let name = item.file_name().to_string_lossy().to_string();
            if names::ignored(&name) {
                continue;
            }
            if !item.path().is_dir() || !space_dirs.contains_key(&name.to_lowercase()) {
                if item.path().is_dir() {
                    self.tell(format!("newspace:{name}"), Event::NewSpaceFolder { name });
                }
                continue;
            }
            walk(&root, &item.path(), &mut |rel, is_dir| {
                if rel.components().count() < 2 {
                    return; // the space folder itself
                }
                let k = key(rel);
                match index.get(&k) {
                    Some((kind, id)) if (*kind == Kind::Folder) == is_dir => {
                        seen.insert(k);
                        if *kind == Kind::File {
                            changed.push(*id);
                        }
                    }
                    _ if is_dir => new_dirs.push(rel.to_path_buf()),
                    _ => new_files.push(rel.to_path_buf()),
                }
            });
        }

        // Changed content
        for id in changed {
            let Some(entry) = self.state.files.get(&id).cloned() else { continue };
            let Some(rel) = self.state.path(Kind::File, id) else { continue };
            if self.dirty(&rel, &entry) {
                self.upload_change(id, &rel, &entry);
            }
        }

        let missing: Vec<(Kind, i64)> = index
            .iter()
            .filter(|(k, _)| !seen.contains(*k))
            .map(|(_, v)| *v)
            .collect();
        let mut missing_folders: Vec<i64> =
            missing.iter().filter(|(k, _)| *k == Kind::Folder).map(|(_, id)| *id).collect();
        let mut missing_files: Vec<i64> =
            missing.iter().filter(|(k, _)| *k == Kind::File).map(|(_, id)| *id).collect();

        // A renamed or moved folder: a new folder with the same content as one that went missing
        new_dirs.sort_by_key(|p| p.components().count());
        let mut moved_any = false;
        for dir in &new_dirs {
            let names_here = child_names(&self.store.abs(dir));
            if let Some(pos) = missing_folders.iter().position(|id| {
                let mine = self.state_child_names(*id);
                !mine.is_empty() && mine == names_here
            }) {
                let id = missing_folders.remove(pos);
                if self.move_folder_to(id, dir) {
                    moved_any = true;
                }
            }
        }
        if moved_any {
            return true;
        }

        // New folders (parents first)
        for dir in &new_dirs {
            self.create_folder_from(dir);
        }

        // New files: a moved/renamed one (same size and time as one that went missing) or really new
        for rel in &new_files {
            let path = self.store.abs(rel);
            let (size, time) = match (std::fs::metadata(&path), mtime(&path)) {
                (Ok(m), Some(t)) => (m.len(), t),
                _ => continue,
            };
            let same = missing_files.iter().position(|id| {
                self.state.files.get(id).is_some_and(|e| e.size == size && e.mtime == time)
            });
            match same {
                Some(pos) => {
                    let id = missing_files.remove(pos);
                    self.move_file_to(id, rel);
                }
                None => self.create_file_from(rel),
            }
        }

        // Deleted here
        let total = self.state.files.len() + self.state.folders.len();
        let deletions = missing_files.len() + missing_folders.len();
        if deletions > MASS_DELETE && deletions * 3 > total {
            self.tell(format!("massdelete:{}", self.state.cursor), Event::ManyDeletes { count: deletions });
            self.restore(missing_files, missing_folders);
            return false;
        }
        // Folders first: deleting a folder takes its content to the trash too
        missing_folders.sort_by_key(|id| self.state.path(Kind::Folder, *id).map(|p| p.components().count()));
        for id in missing_folders {
            if !self.state.folders.contains_key(&id) {
                continue; // already gone with its parent
            }
            match self.api.delete_folder(id) {
                Ok(()) | Err(ApiError::Status(404, _)) => {
                    for (k, i) in self.state.subtree(id) {
                        self.state.entries_mut(k).remove(&i);
                    }
                }
                Err(_) => {}
            }
        }
        for id in missing_files {
            let Some(entry) = self.state.files.get(&id).cloned() else { continue };
            match self.api.delete_file(id) {
                Ok(()) | Err(ApiError::Status(404, _)) => {
                    self.state.files.remove(&id);
                }
                Err(e) if matches!(e.status(), Some(409 | 423)) => {
                    // Checked out by someone else: it cannot be deleted, so it comes back
                    self.tell(format!("busy:{id}:{}", entry.version), Event::Busy { name: entry.name.clone() });
                    self.restore(vec![id], vec![]);
                }
                Err(_) => {}
            }
        }
        false
    }

    fn state_child_names(&self, folder: i64) -> Vec<String> {
        let mut names: Vec<String> = [Kind::Folder, Kind::File]
            .iter()
            .flat_map(|k| {
                self.state
                    .entries(*k)
                    .values()
                    .filter(|e| e.parent_id == Some(folder))
                    .map(|e| e.local_name.to_lowercase())
            })
            .collect();
        names.sort();
        names
    }

    /// Space and folder for a local folder path (relative to the sync folder).
    fn place_of(&self, dir: &Path) -> Option<(i64, Option<i64>)> {
        let mut parts = dir.components();
        let space_dir = parts.next()?.as_os_str().to_string_lossy().to_lowercase();
        let space_id = *self.state.spaces.iter().find(|(_, s)| s.dir.to_lowercase() == space_dir)?.0;
        if dir.components().count() == 1 {
            return Some((space_id, None));
        }
        match self.state.index().get(&key(dir)) {
            Some((Kind::Folder, id)) => Some((space_id, Some(*id))),
            _ => None,
        }
    }

    fn local_name(rel: &Path) -> String {
        rel.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default()
    }

    fn create_folder_from(&mut self, dir: &Path) {
        let Some((space_id, parent)) = dir.parent().and_then(|p| self.place_of(p)) else { return };
        if !self.state.spaces.get(&space_id).is_some_and(|s| s.writable) {
            return;
        }
        let name = Self::local_name(dir);
        match self.api.create_folder(space_id, parent, &name) {
            Ok(item) => {
                let _ = self.store.mark_dir(dir, &item);
                self.state.folders.insert(
                    item.id,
                    Entry {
                        space_id,
                        parent_id: parent,
                        name: item.name,
                        local_name: name,
                        ..Default::default()
                    },
                );
            }
            Err(_) => {}
        }
    }

    fn create_file_from(&mut self, rel: &Path) {
        let Some((space_id, folder)) = rel.parent().and_then(|p| self.place_of(p)) else { return };
        if !self.state.spaces.get(&space_id).is_some_and(|s| s.writable) {
            return;
        }
        let name = Self::local_name(rel);
        let path = self.store.abs(rel);
        let (Ok(data), Some(time)) = (std::fs::read(&path), mtime(&path)) else { return };
        // Still being written (changed while reading): next time
        if mtime(&path) != Some(time) {
            return;
        }
        match self.api.create_file(space_id, folder, &name, &data) {
            Ok(item) => {
                let time = self.store.mark_uploaded(rel, &item).unwrap_or(time);
                self.state.files.insert(
                    item.id,
                    Entry {
                        space_id,
                        parent_id: folder,
                        name: item.name.clone(),
                        local_name: name,
                        version: item.version,
                        size: data.len() as u64,
                        mtime: time,
                        read_only: false,
                        hash: self.store.fingerprint(rel),
                    },
                );
            }
            Err(e) if matches!(e.status(), Some(413 | 415 | 422)) => {
                self.tell(format!("unsupported:{}", key(rel)), Event::NotSupported { name });
            }
            Err(_) => {}
        }
    }

    fn upload_change(&mut self, id: i64, rel: &Path, entry: &Entry) {
        let path = self.store.abs(rel);
        let (Ok(data), Some(time)) = (std::fs::read(&path), mtime(&path)) else { return };
        if mtime(&path) != Some(time) {
            return; // still being written
        }
        match self.api.save(id, entry.version, &data) {
            Ok(item) => {
                let time = self.store.mark_uploaded(rel, &item).unwrap_or(time);
                let hash = self.store.fingerprint(rel);
                if let Some(e) = self.state.files.get_mut(&id) {
                    e.version = item.version;
                    e.size = data.len() as u64;
                    e.mtime = time;
                    e.hash = hash;
                }
            }
            Err(ApiError::Status(409, code)) if code == "sync_conflict" => {
                // Someone else saved meanwhile: keep mine as a copy, put theirs in place
                let copy = self.conflict_name(rel);
                if std::fs::rename(&path, self.store.abs(&copy)).is_ok() {
                    self.tell(
                        format!("conflict:{id}:{}", entry.version),
                        Event::Conflict {
                            name: entry.name.clone(),
                            copy: Self::local_name(&copy),
                        },
                    );
                    self.refetch(id, rel);
                }
            }
            Err(e) if matches!(e.status(), Some(409 | 423)) => {
                self.tell(format!("busy:{id}:{}", entry.version), Event::Busy { name: entry.name.clone() });
            }
            Err(e) if matches!(e.status(), Some(413 | 415)) => {
                self.tell(format!("unsupported:{id}"), Event::NotSupported { name: entry.name.clone() });
            }
            Err(_) => {}
        }
    }

    /// The server's current content of a file, written as in sync.
    fn refetch(&mut self, id: i64, rel: &Path) {
        let Ok((version, data)) = self.api.download_current(id) else { return };
        let Some(entry) = self.state.files.get(&id).cloned() else { return };
        let item = Item {
            kind: "file".into(),
            id,
            space_id: entry.space_id,
            parent_id: entry.parent_id,
            name: entry.name.clone(),
            size: data.len() as u64,
            version,
            modified: String::new(),
            deleted: false,
            read_only: entry.read_only,
        };
        if let Ok(time) = self.store.write_synced(rel, &item, &data) {
            let hash = self.store.fingerprint(rel);
            if let Some(e) = self.state.files.get_mut(&id) {
                e.version = version;
                e.size = data.len() as u64;
                e.mtime = time;
                e.hash = hash;
            }
        }
    }

    fn move_folder_to(&mut self, id: i64, dir: &Path) -> bool {
        let Some((space_id, parent)) = dir.parent().and_then(|p| self.place_of(p)) else { return false };
        let Some(entry) = self.state.folders.get(&id).cloned() else { return false };
        if space_id != entry.space_id {
            return false; // across spaces: handled as new + deleted
        }
        let name = Self::local_name(dir);
        match self.api.move_folder(id, &name, parent) {
            Ok(item) => {
                if let Some(e) = self.state.folders.get_mut(&id) {
                    e.parent_id = parent;
                    e.name = item.name;
                    e.local_name = name;
                }
                true
            }
            Err(_) => false,
        }
    }

    fn move_file_to(&mut self, id: i64, rel: &Path) {
        let Some(entry) = self.state.files.get(&id).cloned() else { return };
        let Some((space_id, folder)) = rel.parent().and_then(|p| self.place_of(p)) else { return };
        let name = Self::local_name(rel);
        if space_id != entry.space_id {
            // Into another space: a new file there, the old one to the trash
            self.create_file_from(rel);
            if self.api.delete_file(id).is_ok() {
                self.state.files.remove(&id);
            }
            return;
        }
        match self.api.move_file(id, &name, folder) {
            Ok(item) => {
                if let Some(e) = self.state.files.get_mut(&id) {
                    e.parent_id = folder;
                    e.name = item.name;
                    e.local_name = name;
                }
            }
            Err(e) if e.status() == Some(422) => {
                // Another file type: a new file instead
                self.create_file_from(rel);
            }
            Err(e) if matches!(e.status(), Some(409 | 423)) => {
                self.tell(format!("busy:{id}:{}", entry.version), Event::Busy { name: entry.name.clone() });
            }
            Err(_) => {}
        }
    }

    /// Puts files and folders back that went missing locally but stay on the server.
    fn restore(&mut self, files: Vec<i64>, folders: Vec<i64>) {
        let mut folders = folders;
        folders.sort_by_key(|id| self.state.path(Kind::Folder, *id).map(|p| p.components().count()));
        for id in folders {
            if let Some(rel) = self.state.path(Kind::Folder, id) {
                let _ = self.store.make_dir(&rel);
            }
        }
        for id in files {
            let (Some(rel), Some(entry)) = (self.state.path(Kind::File, id), self.state.files.get(&id).cloned()) else {
                continue;
            };
            let item = Item {
                kind: "file".into(),
                id,
                space_id: entry.space_id,
                parent_id: entry.parent_id,
                name: entry.name.clone(),
                size: entry.size,
                version: entry.version,
                modified: String::new(),
                deleted: false,
                read_only: entry.read_only,
            };
            if let Ok(time) = self.store.put_file(&rel, &item) {
                let hash = self.store.fingerprint(&rel);
                if let Some(e) = self.state.files.get_mut(&id) {
                    e.mtime = time;
                    e.hash = hash;
                }
            }
        }
    }
}

/// Calls `visit(relative path, is folder)` for everything below `dir` (not following links), skipping helper files.
fn walk(root: &Path, dir: &Path, visit: &mut dyn FnMut(&Path, bool)) {
    let Ok(rel) = dir.strip_prefix(root) else { return };
    visit(rel, true);
    let Ok(items) = std::fs::read_dir(dir) else { return };
    let mut items: Vec<_> = items.flatten().collect();
    items.sort_by_key(|i| i.file_name());
    for item in items {
        let name = item.file_name().to_string_lossy().to_string();
        if names::ignored(&name) {
            continue;
        }
        let Ok(kind) = item.file_type() else { continue };
        let path = item.path();
        if kind.is_symlink() {
            continue;
        }
        if kind.is_dir() {
            walk(root, &path, visit);
        } else if let Ok(rel) = path.strip_prefix(root) {
            visit(rel, false);
        }
    }
}

fn child_names(dir: &Path) -> Vec<String> {
    let mut names: Vec<String> = std::fs::read_dir(dir)
        .map(|items| {
            items
                .flatten()
                .map(|i| i.file_name().to_string_lossy().to_string())
                .filter(|n| !names::ignored(n))
                .map(|n| n.to_lowercase())
                .collect()
        })
        .unwrap_or_default();
    names.sort();
    names
}

/// Removes a folder with everything in it, also read-only files (checked out by others).
fn remove_all(path: &Path) -> std::io::Result<()> {
    if !path.exists() {
        return Ok(());
    }
    let mut stack = vec![path.to_path_buf()];
    while let Some(dir) = stack.pop() {
        if let Ok(items) = std::fs::read_dir(&dir) {
            for item in items.flatten() {
                let p = item.path();
                if p.is_dir() {
                    stack.push(p);
                } else if let Ok(meta) = std::fs::metadata(&p) {
                    let mut perms = meta.permissions();
                    #[allow(clippy::permissions_set_readonly_false)]
                    perms.set_readonly(false);
                    let _ = std::fs::set_permissions(&p, perms);
                }
            }
        }
    }
    std::fs::remove_dir_all(path)
}

/// Days since 1970 → (year, month, day) (Howard Hinnant's algorithm).
fn civil(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let y = yoe + era * 400 + i64::from(m <= 2);
    (y, m, d)
}

#[cfg(test)]
mod tests {
    #[test]
    fn dates_from_days() {
        assert_eq!(super::civil(0), (1970, 1, 1));
        assert_eq!(super::civil(20_748), (2026, 10, 22));
    }
}
