//! Windows: the sync folder as a cloud folder like OneDrive (Cloud Files API, via the `cloud-filter` crate).
//!
//! - Registered as "OfficeHub" in Explorer's navigation pane, with sync status icons.
//! - Files are placeholders: name, size and date are there, the content downloads when a file is opened
//!   (`fetch_data`), with progress in Explorer.
//! - "Always keep on this device" downloads, "Free up space" removes the local copy again (`state_changed`).
//! - Deleting and renaming are allowed here and passed on by the engine's scan.

use std::io;
use std::path::{Path, PathBuf};

use cloud_filter::error::{CResult, CloudErrorKind};
use cloud_filter::filter::{info, ticket, Request, SyncFilter};
use cloud_filter::metadata::Metadata;
use cloud_filter::placeholder::{ConvertOptions, PinState, Placeholder, UpdateOptions};
use cloud_filter::placeholder_file::PlaceholderFile;
use cloud_filter::root::{
    Connection, HydrationType, PopulationType, ProtectionMode, SecurityId, Session, SyncRootId, SyncRootIdBuilder,
    SyncRootInfo,
};
use cloud_filter::utility::{FileTime, WriteAt};

use super::api::{Api, Item};
use super::store::{mtime, Store};

const PROVIDER: &str = "OfficeHub";
/// Downloads in pieces of this size (a multiple of 4 KiB, as the Cloud Files API wants)
const CHUNK: u64 = 4 * 1024 * 1024;

/// What a placeholder stands for: the file's id and version on the server.
pub fn blob(id: i64, version: i64) -> Vec<u8> {
    format!("{{\"id\":{id},\"v\":{version}}}").into_bytes()
}

pub fn parse_blob(blob: &[u8]) -> Option<(i64, i64)> {
    let value: serde_json::Value = serde_json::from_slice(blob).ok()?;
    Some((value.get("id")?.as_i64()?, value.get("v")?.as_i64()?))
}

/// "2026-10-22T18:00:00.123456" (UTC, from the server) → Windows file time.
fn file_time(iso: &str) -> FileTime {
    parse_iso(iso)
        .and_then(|secs| FileTime::from_unix_time(secs).ok())
        .unwrap_or_else(FileTime::now)
}

fn parse_iso(iso: &str) -> Option<i64> {
    let date = iso.get(0..10)?;
    let time = iso.get(11..19)?;
    let mut d = date.split('-').map(|p| p.parse::<i64>().ok());
    let (y, m, day) = (d.next()??, d.next()??, d.next()??);
    let mut t = time.split(':').map(|p| p.parse::<i64>().ok());
    let (h, min, s) = (t.next()??, t.next()??, t.next()??);
    // Days from civil (Howard Hinnant)
    let y2 = if m <= 2 { y - 1 } else { y };
    let era = y2.div_euclid(400);
    let yoe = y2 - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    Some(days * 86_400 + h * 3600 + min * 60 + s)
}

fn metadata(item: &Item) -> Metadata {
    let time = file_time(&item.modified);
    Metadata::file().size(item.size).written(time).created(time).changed(time)
}

fn other<E: std::fmt::Debug>(e: E) -> io::Error {
    io::Error::other(format!("{e:?}"))
}

pub struct CloudStore {
    pub root: PathBuf,
}

impl CloudStore {
    fn create_placeholder(&self, rel: &Path, item: &Item) -> io::Result<i128> {
        let path = self.abs(rel);
        let parent = path.parent().ok_or_else(|| other("no parent"))?.to_path_buf();
        let name = path.file_name().ok_or_else(|| other("no name"))?;
        PlaceholderFile::new(name)
            .metadata(metadata(item))
            .mark_in_sync()
            .overwrite()
            .blob(blob(item.id, item.version))
            .create::<PathBuf>(parent)
            .map_err(other)?;
        mtime(&path).ok_or_else(|| other("no modification time"))
    }

    fn convert(&self, path: &Path, data: Vec<u8>, dir: bool) -> io::Result<()> {
        let mut placeholder = Placeholder::open(path).map_err(other)?;
        let is_placeholder = placeholder.info().ok().flatten().is_some();
        if is_placeholder {
            placeholder
                .update(UpdateOptions::default().blob(&data).mark_in_sync(), None)
                .map_err(other)?;
        } else {
            let mut options = ConvertOptions::default().mark_in_sync().blob(data);
            if dir {
                options = options.has_children();
            }
            placeholder.convert_to_placeholder(options, None).map_err(other)?;
        }
        Ok(())
    }
}

impl Store for CloudStore {
    fn root(&self) -> &Path {
        &self.root
    }

    fn make_dir(&self, rel: &Path) -> io::Result<()> {
        let path = self.abs(rel);
        std::fs::create_dir_all(&path)?;
        let _ = self.convert(&path, b"{}".to_vec(), true);
        Ok(())
    }

    fn mark_dir(&self, rel: &Path, item: &Item) -> io::Result<()> {
        self.convert(&self.abs(rel), blob(item.id, 0), true)
    }

    fn put_file(&self, rel: &Path, item: &Item) -> io::Result<i128> {
        self.create_placeholder(rel, item)
    }

    fn replace_file(&self, rel: &Path, item: &Item) -> io::Result<i128> {
        let path = self.abs(rel);
        self.set_read_only(rel, false);
        let data = blob(item.id, item.version);
        let updated = Placeholder::options().write_access().exclusive().open(&path).and_then(|mut p| {
            let pinned = p.info().ok().flatten().is_some_and(|i| i.pin_state() == PinState::Pinned);
            p.update(
                UpdateOptions::default().metadata(metadata(item)).blob(&data).dehydrate().mark_in_sync(),
                None,
            )?;
            if pinned {
                // "Always keep on this device": fetch the new version right away
                let _ = p.hydrate(..);
            }
            Ok(())
        });
        if updated.is_err() {
            // Not a placeholder (or in use): put a fresh one in its place
            std::fs::remove_file(&path)?;
            return self.create_placeholder(rel, item);
        }
        mtime(&path).ok_or_else(|| other("no modification time"))
    }

    fn write_synced(&self, rel: &Path, item: &Item, data: &[u8]) -> io::Result<i128> {
        let path = self.abs(rel);
        std::fs::write(&path, data)?;
        self.convert(&path, blob(item.id, item.version), false)?;
        mtime(&path).ok_or_else(|| other("no modification time"))
    }

    fn mark_uploaded(&self, rel: &Path, item: &Item) -> io::Result<i128> {
        let path = self.abs(rel);
        self.convert(&path, blob(item.id, item.version), false)?;
        mtime(&path).ok_or_else(|| other("no modification time"))
    }
}

/// Answers Windows when a placeholder's content is needed, and follows "Always keep" / "Free up space".
pub struct Filter {
    pub api: Api,
}

impl SyncFilter for Filter {
    fn fetch_data(&self, request: Request, ticket: ticket::FetchData, info: info::FetchData) -> CResult<()> {
        let (id, version) = parse_blob(request.file_blob()).ok_or(CloudErrorKind::InvalidRequest)?;
        let range = info.required_file_range();
        let mut position = range.start;
        while position < range.end {
            let end = (position + CHUNK).min(range.end);
            let data = self.api.download(id, version, position, end).map_err(|_| CloudErrorKind::Unsuccessful)?;
            if data.is_empty() {
                return Err(CloudErrorKind::Unsuccessful);
            }
            // Whole 4 KiB blocks, except at the very end of the file
            let mut usable = data.len() as u64;
            if position + usable < range.end {
                usable -= usable % 4096;
            }
            let usable = usize::try_from(usable).unwrap_or(0);
            if usable == 0 {
                return Err(CloudErrorKind::Unsuccessful);
            }
            ticket.write_at(&data[..usable], position).map_err(|_| CloudErrorKind::Unsuccessful)?;
            position += usable as u64;
            let _ = ticket.report_progress(range.end, position);
        }
        Ok(())
    }

    fn fetch_placeholders(
        &self,
        _request: Request,
        ticket: ticket::FetchPlaceholders,
        _info: info::FetchPlaceholders,
    ) -> CResult<()> {
        // All placeholders are made by the engine ahead of time
        ticket.pass_with_placeholder(&mut []).map_err(|_| CloudErrorKind::Unsuccessful)
    }

    fn delete(&self, _request: Request, ticket: ticket::Delete, _info: info::Delete) -> CResult<()> {
        ticket.pass().map_err(|_| CloudErrorKind::Unsuccessful)
    }

    fn rename(&self, _request: Request, ticket: ticket::Rename, _info: info::Rename) -> CResult<()> {
        ticket.pass().map_err(|_| CloudErrorKind::Unsuccessful)
    }

    fn state_changed(&self, changes: Vec<PathBuf>) {
        for path in changes {
            follow_pin(&path, 0);
        }
    }
}

/// "Always keep on this device" downloads now, "Free up space" lets go of the local copy.
fn follow_pin(path: &Path, depth: usize) {
    if depth > 64 {
        return;
    }
    if path.is_dir() {
        if let Ok(items) = std::fs::read_dir(path) {
            for item in items.flatten() {
                follow_pin(&item.path(), depth + 1);
            }
        }
        return;
    }
    let Ok(mut placeholder) = Placeholder::open(path) else { return };
    let Ok(Some(info)) = placeholder.info() else { return };
    match info.pin_state() {
        PinState::Pinned => {
            let path = path.to_path_buf();
            // In the background: a large file must not hold up Explorer
            std::thread::spawn(move || {
                if let Ok(mut p) = Placeholder::open(&path) {
                    let _ = p.hydrate(..);
                }
            });
        }
        PinState::Unpinned if info.is_in_sync() => {
            let _ = placeholder.update(UpdateOptions::default().dehydrate(), None);
        }
        _ => {}
    }
}

fn root_id(login: &str) -> io::Result<SyncRootId> {
    Ok(SyncRootIdBuilder::new(PROVIDER)
        .user_security_id(SecurityId::current_user().map_err(other)?)
        .account_name(login)
        .build())
}

/// Registers the sync folder with Windows (Explorer entry, icons) and connects the filter.
pub fn connect(root: &Path, login: &str, display_name: &str, api: Api) -> io::Result<Connection<Filter>> {
    std::fs::create_dir_all(root)?;
    let id = root_id(login)?;
    if !id.is_registered().map_err(other)? {
        let exe = std::env::current_exe()?;
        id.register(
            SyncRootInfo::default()
                .with_display_name(display_name)
                .with_icon(format!("{},0", exe.display()))
                .with_version(env!("CARGO_PKG_VERSION"))
                .with_hydration_type(HydrationType::Full)
                .with_population_type(PopulationType::AlwaysFull)
                .with_protection_mode(ProtectionMode::Unknown)
                .with_allow_pinning(true)
                .with_path(root)
                .map_err(other)?,
        )
        .map_err(other)?;
    }
    Session::new().connect(root, Filter { api }).map_err(other)
}

/// Takes the folder out of Explorer's navigation pane (after "Stop syncing"); the files stay where they are.
pub fn unregister(login: &str) -> io::Result<()> {
    let id = root_id(login)?;
    if id.is_registered().map_err(other)? {
        id.unregister().map_err(other)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blobs_round_trip() {
        assert_eq!(parse_blob(&blob(42, 7)), Some((42, 7)));
        assert_eq!(parse_blob(b"{}"), None);
    }

    #[test]
    fn server_times_become_unix_seconds() {
        assert_eq!(parse_iso("1970-01-01T00:00:00"), Some(0));
        assert_eq!(parse_iso("2026-10-22T18:00:00.123456"), Some(1_792_692_000));
    }
}
