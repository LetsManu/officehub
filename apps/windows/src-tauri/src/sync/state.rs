//! What the sync knows: every space, folder and file with its place on this computer and the state it was in when
//! both sides last agreed. Saved as JSON next to the app's settings.

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use super::names;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub enum Kind {
    Folder,
    File,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct SpaceEntry {
    pub name: String,
    /// The folder's name in the sync folder (Windows-safe and unique)
    pub dir: String,
    pub writable: bool,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Entry {
    pub space_id: i64,
    pub parent_id: Option<i64>,
    /// The name on the server
    pub name: String,
    /// The name on this computer (Windows-safe and unique in its folder)
    pub local_name: String,
    pub version: i64,
    pub size: u64,
    /// Modification time of the local file when both sides last agreed (nanoseconds since 1970)
    pub mtime: i128,
    pub read_only: bool,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct State {
    pub server: String,
    pub login: String,
    pub cursor: i64,
    pub spaces: BTreeMap<i64, SpaceEntry>,
    pub folders: BTreeMap<i64, Entry>,
    pub files: BTreeMap<i64, Entry>,
}

const MAX_DEPTH: usize = 64;

impl State {
    pub fn load(file: &Path) -> Option<State> {
        let text = std::fs::read_to_string(file).ok()?;
        serde_json::from_str(&text).ok()
    }

    pub fn save(&self, file: &Path) -> std::io::Result<()> {
        if let Some(dir) = file.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let text = serde_json::to_string(self).map_err(std::io::Error::other)?;
        // Write next to it, then replace: a crash never leaves half a file
        let temp = file.with_extension("tmp");
        std::fs::write(&temp, text)?;
        std::fs::rename(&temp, file)
    }

    pub fn entries(&self, kind: Kind) -> &BTreeMap<i64, Entry> {
        match kind {
            Kind::Folder => &self.folders,
            Kind::File => &self.files,
        }
    }

    pub fn entries_mut(&mut self, kind: Kind) -> &mut BTreeMap<i64, Entry> {
        match kind {
            Kind::Folder => &mut self.folders,
            Kind::File => &mut self.files,
        }
    }

    /// The folder on this computer for a space folder (`None`) or a folder, relative to the sync folder.
    pub fn dir_path(&self, space_id: i64, folder: Option<i64>) -> Option<PathBuf> {
        let space = self.spaces.get(&space_id)?;
        let mut parts = Vec::new();
        let mut current = folder;
        while let Some(id) = current {
            let entry = self.folders.get(&id)?;
            if entry.space_id != space_id || parts.len() > MAX_DEPTH {
                return None;
            }
            parts.push(entry.local_name.clone());
            current = entry.parent_id;
        }
        let mut path = PathBuf::from(&space.dir);
        for part in parts.iter().rev() {
            path.push(part);
        }
        Some(path)
    }

    /// Where an entry lives on this computer, relative to the sync folder.
    pub fn path(&self, kind: Kind, id: i64) -> Option<PathBuf> {
        let entry = self.entries(kind).get(&id)?;
        match kind {
            Kind::Folder => self.dir_path(entry.space_id, Some(id)),
            Kind::File => Some(self.dir_path(entry.space_id, entry.parent_id)?.join(&entry.local_name)),
        }
    }

    /// Lower-case relative path → entry, for matching what is on the disk.
    pub fn index(&self) -> HashMap<String, (Kind, i64)> {
        let mut index = HashMap::new();
        for kind in [Kind::Folder, Kind::File] {
            for id in self.entries(kind).keys() {
                if let Some(path) = self.path(kind, *id) {
                    index.insert(key(&path), (kind, *id));
                }
            }
        }
        index
    }

    /// A local name for `name` in a folder that no other entry (or space folder) uses yet.
    pub fn free_name(&self, space_id: i64, parent: Option<i64>, name: &str, me: Option<(Kind, i64)>) -> String {
        let safe = names::windows_safe(name);
        let siblings: Vec<&str> = [Kind::Folder, Kind::File]
            .iter()
            .flat_map(|kind| {
                self.entries(*kind)
                    .iter()
                    .filter(move |(id, e)| {
                        e.space_id == space_id && e.parent_id == parent && me != Some((*kind, **id))
                    })
                    .map(|(_, e)| e.local_name.as_str())
            })
            .collect();
        names::unique(&safe, |candidate| siblings.iter().any(|s| s.eq_ignore_ascii_case(candidate)))
    }

    /// A folder name for a space, unique among the spaces.
    pub fn free_space_dir(&self, space_id: i64, name: &str) -> String {
        let safe = names::windows_safe(name);
        names::unique(&safe, |candidate| {
            self.spaces
                .iter()
                .any(|(id, s)| *id != space_id && s.dir.eq_ignore_ascii_case(candidate))
        })
    }

    /// The entry and everything below a folder (deepest first), to forget them together.
    pub fn subtree(&self, folder: i64) -> Vec<(Kind, i64)> {
        let mut out = Vec::new();
        let mut stack = vec![folder];
        while let Some(current) = stack.pop() {
            if out.len() > 1_000_000 {
                break;
            }
            for (id, e) in &self.files {
                if e.parent_id == Some(current) {
                    out.push((Kind::File, *id));
                }
            }
            for (id, e) in &self.folders {
                if e.parent_id == Some(current) {
                    stack.push(*id);
                }
            }
            out.push((Kind::Folder, current));
        }
        out
    }

    pub fn forget_space(&mut self, space_id: i64) {
        self.spaces.remove(&space_id);
        self.folders.retain(|_, e| e.space_id != space_id);
        self.files.retain(|_, e| e.space_id != space_id);
    }
}

/// How paths are compared: Windows ignores case, and "/" and "\" are the same.
pub fn key(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/").to_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(space: i64, parent: Option<i64>, name: &str) -> Entry {
        Entry { space_id: space, parent_id: parent, name: name.into(), local_name: name.into(), ..Default::default() }
    }

    fn sample() -> State {
        let mut s = State::default();
        s.spaces.insert(1, SpaceEntry { name: "Marketing".into(), dir: "Marketing".into(), writable: true });
        s.folders.insert(10, entry(1, None, "Angebote"));
        s.folders.insert(11, entry(1, Some(10), "2026"));
        s.files.insert(100, entry(1, Some(11), "Plan.docx"));
        s.files.insert(101, entry(1, None, "Liste.xlsx"));
        s
    }

    #[test]
    fn paths_follow_the_folders() {
        let s = sample();
        assert_eq!(s.path(Kind::File, 100), Some(PathBuf::from("Marketing/Angebote/2026/Plan.docx")));
        assert_eq!(s.path(Kind::File, 101), Some(PathBuf::from("Marketing/Liste.xlsx")));
        assert_eq!(s.index().get("marketing/angebote/2026/plan.docx"), Some(&(Kind::File, 100)));
    }

    #[test]
    fn free_names_avoid_siblings_ignoring_case() {
        let s = sample();
        assert_eq!(s.free_name(1, None, "liste.xlsx", None), "liste (2).xlsx");
        assert_eq!(s.free_name(1, None, "Liste.xlsx", Some((Kind::File, 101))), "Liste.xlsx");
        assert_eq!(s.free_name(1, Some(10), "Plan.docx", None), "Plan.docx");
    }

    #[test]
    fn subtree_lists_everything_below() {
        let s = sample();
        let mut sub = s.subtree(10);
        sub.sort();
        assert_eq!(sub, vec![(Kind::Folder, 10), (Kind::Folder, 11), (Kind::File, 100)]);
    }

    #[test]
    fn broken_parents_give_no_path() {
        let mut s = sample();
        s.folders.get_mut(&11).map(|f| f.parent_id = Some(999));
        assert_eq!(s.path(Kind::File, 100), None);
    }
}
