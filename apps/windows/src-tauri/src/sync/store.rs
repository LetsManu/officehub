//! How server files become files on this computer.
//!
//! On Windows (cloud.rs) they are placeholders, like OneDrive's "Files On-Demand": they show in Explorer with name,
//! size and date and only download when opened (or when "Always keep on this device" is chosen). Everywhere else
//! (and for the tests) `FullStore` downloads every file right away.

use std::io;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use super::api::{Api, Item};

/// Nanoseconds since 1970 of a file's last change, as the file system reports it.
pub fn mtime(path: &Path) -> Option<i128> {
    let modified = std::fs::metadata(path).ok()?.modified().ok()?;
    let since = modified.duration_since(UNIX_EPOCH).ok()?;
    Some(i128::try_from(since.as_nanos()).unwrap_or(i128::MAX))
}

pub trait Store: Send + Sync {
    fn root(&self) -> &Path;

    fn abs(&self, rel: &Path) -> PathBuf {
        self.root().join(rel)
    }

    /// A folder for a space or a server folder.
    fn make_dir(&self, rel: &Path) -> io::Result<()>;

    /// A local folder now known to the server.
    fn mark_dir(&self, rel: &Path, item: &Item) -> io::Result<()>;

    /// A file standing for the server's file. Returns the modification time to remember.
    fn put_file(&self, rel: &Path, item: &Item) -> io::Result<i128>;

    /// The server has a newer version of an unchanged local file.
    fn replace_file(&self, rel: &Path, item: &Item) -> io::Result<i128>;

    /// Content already downloaded (after a conflict): write it as in sync.
    fn write_synced(&self, rel: &Path, item: &Item, data: &[u8]) -> io::Result<i128>;

    /// A local file has been uploaded and is now in sync.
    fn mark_uploaded(&self, rel: &Path, item: &Item) -> io::Result<i128>;

    /// Only readable while someone else has it checked out.
    fn set_read_only(&self, rel: &Path, read_only: bool) {
        let path = self.abs(rel);
        if let Ok(meta) = std::fs::metadata(&path) {
            let mut perms = meta.permissions();
            if perms.readonly() != read_only {
                #[allow(clippy::permissions_set_readonly_false)]
                perms.set_readonly(read_only);
                let _ = std::fs::set_permissions(&path, perms);
            }
        }
    }
}

/// Every file downloaded in full (no placeholders).
pub struct FullStore {
    pub root: PathBuf,
    pub api: Api,
}

impl FullStore {
    fn download(&self, rel: &Path, item: &Item) -> io::Result<i128> {
        let data = self
            .api
            .download(item.id, item.version, 0, 0)
            .map_err(|e| io::Error::other(e.to_string()))?;
        self.write_synced(rel, item, &data)
    }
}

impl Store for FullStore {
    fn root(&self) -> &Path {
        &self.root
    }

    fn make_dir(&self, rel: &Path) -> io::Result<()> {
        std::fs::create_dir_all(self.abs(rel))
    }

    fn mark_dir(&self, _rel: &Path, _item: &Item) -> io::Result<()> {
        Ok(())
    }

    fn put_file(&self, rel: &Path, item: &Item) -> io::Result<i128> {
        self.download(rel, item)
    }

    fn replace_file(&self, rel: &Path, item: &Item) -> io::Result<i128> {
        self.set_read_only(rel, false);
        self.download(rel, item)
    }

    fn write_synced(&self, rel: &Path, _item: &Item, data: &[u8]) -> io::Result<i128> {
        let path = self.abs(rel);
        let temp = path.with_extension("officehub-partial");
        std::fs::write(&temp, data)?;
        std::fs::rename(&temp, &path)?;
        mtime(&path).ok_or_else(|| io::Error::other("no modification time"))
    }

    fn mark_uploaded(&self, rel: &Path, _item: &Item) -> io::Result<i128> {
        mtime(&self.abs(rel)).ok_or_else(|| io::Error::other("no modification time"))
    }
}
