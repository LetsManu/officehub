//! The portal's sync API (backend routers/sync.py), signed in with an app password.

use std::io::Read;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct SpaceInfo {
    pub id: i64,
    pub name: String,
    pub writable: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Item {
    pub kind: String, // "folder" or "file"
    pub id: i64,
    pub space_id: i64,
    pub parent_id: Option<i64>,
    pub name: String,
    #[serde(default)]
    pub size: u64,
    #[serde(default)]
    pub version: i64,
    pub modified: String,
    #[serde(default)]
    pub deleted: bool,
    #[serde(default)]
    pub read_only: bool,
}

impl Item {
    pub fn is_folder(&self) -> bool {
        self.kind == "folder"
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct Removed {
    pub kind: String,
    pub id: i64,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Changes {
    pub cursor: i64,
    pub reset: bool,
    pub more: bool,
    pub spaces: Vec<SpaceInfo>,
    pub items: Vec<Item>,
    pub removed: Vec<Removed>,
}

#[derive(Debug)]
pub enum ApiError {
    /// The server answered with an error (status, code such as "sync_conflict" or "file_checked_out")
    Status(u16, String),
    /// No connection
    Offline(String),
}

impl ApiError {
    pub fn status(&self) -> Option<u16> {
        match self {
            ApiError::Status(status, _) => Some(*status),
            ApiError::Offline(_) => None,
        }
    }

    pub fn code(&self) -> &str {
        match self {
            ApiError::Status(_, code) => code,
            ApiError::Offline(_) => "offline",
        }
    }
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ApiError::Status(status, code) => write!(f, "HTTP {status} {code}"),
            ApiError::Offline(why) => write!(f, "offline: {why}"),
        }
    }
}

pub type Result<T> = std::result::Result<T, ApiError>;

#[derive(Clone)]
pub struct Api {
    base: String,
    auth: String,
    agent: ureq::Agent,
}

/// Pieces of a query string, escaped.
fn q(value: &str) -> String {
    let mut out = String::new();
    for byte in value.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => out.push(byte as char),
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

impl Api {
    pub fn new(server: &str, login: &str, password: &str) -> Self {
        use base64_engine::encode;
        let agent = ureq::AgentBuilder::new()
            .timeout_connect(Duration::from_secs(10))
            .timeout_read(Duration::from_secs(60))
            .build();
        Api {
            base: server.trim_end_matches('/').to_string(),
            auth: format!("Basic {}", encode(format!("{login}:{password}").as_bytes())),
            agent,
        }
    }

    fn request(&self, method: &str, path: &str) -> ureq::Request {
        self.agent
            .request(method, &format!("{}{}", self.base, path))
            .set("Authorization", &self.auth)
            .set("X-Requested-With", "OfficeHub")
            .set("User-Agent", concat!("OfficeHubApp/", env!("CARGO_PKG_VERSION"), " (windows; sync)"))
    }

    fn answer(result: std::result::Result<ureq::Response, ureq::Error>) -> Result<ureq::Response> {
        match result {
            Ok(response) => Ok(response),
            Err(ureq::Error::Status(status, response)) => {
                let code = response
                    .into_json::<Value>()
                    .ok()
                    .and_then(|v| v.get("code").and_then(Value::as_str).map(str::to_string))
                    .unwrap_or_default();
                Err(ApiError::Status(status, code))
            }
            Err(e) => Err(ApiError::Offline(e.to_string())),
        }
    }

    fn json<T: for<'de> Deserialize<'de>>(response: ureq::Response) -> Result<T> {
        response.into_json::<T>().map_err(|e| ApiError::Offline(e.to_string()))
    }

    /// What changed after `since` (0: the whole tree); waits up to `wait` seconds for something to change.
    pub fn changes(&self, since: i64, wait: u32, space: Option<i64>) -> Result<Changes> {
        let mut path = format!("/api/sync/changes?since={since}&wait={wait}");
        if let Some(space) = space {
            path.push_str(&format!("&space_id={space}"));
        }
        Self::json(Self::answer(self.request("GET", &path).call())?)
    }

    /// Bytes `start..end` (end exclusive) of a file's given version.
    pub fn download(&self, id: i64, version: i64, start: u64, end: u64) -> Result<Vec<u8>> {
        let mut req = self.request("GET", &format!("/api/sync/files/{id}?version={version}"));
        if end > start {
            req = req.set("Range", &format!("bytes={start}-{}", end - 1));
        }
        let response = Self::answer(req.call())?;
        let partial = response.status() == 206;
        let mut data = Vec::new();
        response
            .into_reader()
            .take(1 << 34)
            .read_to_end(&mut data)
            .map_err(|e| ApiError::Offline(e.to_string()))?;
        if !partial && end > start {
            // The server sent the whole file: keep the asked part
            let from = usize::try_from(start).unwrap_or(usize::MAX).min(data.len());
            let to = usize::try_from(end).unwrap_or(usize::MAX).min(data.len());
            data = data[from..to].to_vec();
        }
        Ok(data)
    }

    /// The current content and its version number.
    pub fn download_current(&self, id: i64) -> Result<(i64, Vec<u8>)> {
        let response = Self::answer(self.request("GET", &format!("/api/sync/files/{id}")).call())?;
        let version = response.header("X-File-Version").and_then(|v| v.parse().ok()).unwrap_or(0);
        let mut data = Vec::new();
        response
            .into_reader()
            .take(1 << 34)
            .read_to_end(&mut data)
            .map_err(|e| ApiError::Offline(e.to_string()))?;
        Ok((version, data))
    }

    /// New content, only on top of version `base` (else Status(409, "sync_conflict")).
    pub fn save(&self, id: i64, base: i64, data: &[u8]) -> Result<Item> {
        let req = self.request("PUT", &format!("/api/sync/files/{id}?base={base}"));
        Self::json(Self::answer(req.send_bytes(data))?)
    }

    pub fn create_file(&self, space: i64, folder: Option<i64>, name: &str, data: &[u8]) -> Result<Item> {
        let mut path = format!("/api/sync/files?space_id={space}&name={}", q(name));
        if let Some(folder) = folder {
            path.push_str(&format!("&folder_id={folder}"));
        }
        Self::json(Self::answer(self.request("POST", &path).send_bytes(data))?)
    }

    pub fn move_file(&self, id: i64, name: &str, folder: Option<i64>) -> Result<Item> {
        let req = self.request("PATCH", &format!("/api/sync/files/{id}"));
        Self::json(Self::answer(req.send_json(json!({ "name": name, "folder_id": folder })))?)
    }

    pub fn delete_file(&self, id: i64) -> Result<()> {
        Self::answer(self.request("DELETE", &format!("/api/sync/files/{id}")).call()).map(|_| ())
    }

    pub fn create_folder(&self, space: i64, parent: Option<i64>, name: &str) -> Result<Item> {
        let req = self.request("POST", "/api/sync/folders");
        Self::json(Self::answer(
            req.send_json(json!({ "space_id": space, "parent_id": parent, "name": name })),
        )?)
    }

    pub fn move_folder(&self, id: i64, name: &str, parent: Option<i64>) -> Result<Item> {
        let req = self.request("PATCH", &format!("/api/sync/folders/{id}"));
        Self::json(Self::answer(req.send_json(json!({ "name": name, "parent_id": parent })))?)
    }

    pub fn delete_folder(&self, id: i64) -> Result<()> {
        Self::answer(self.request("DELETE", &format!("/api/sync/folders/{id}")).call()).map(|_| ())
    }
}

/// Base64 without another dependency (only for the sign-in header).
mod base64_engine {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    pub fn encode(data: &[u8]) -> String {
        let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
        for chunk in data.chunks(3) {
            let b = [chunk[0], *chunk.get(1).unwrap_or(&0), *chunk.get(2).unwrap_or(&0)];
            let n = (u32::from(b[0]) << 16) | (u32::from(b[1]) << 8) | u32::from(b[2]);
            for i in 0..4 {
                if i <= chunk.len() {
                    out.push(TABLE[((n >> (18 - 6 * i)) & 63) as usize] as char);
                } else {
                    out.push('=');
                }
            }
        }
        out
    }

    #[cfg(test)]
    mod tests {
        #[test]
        fn encodes_like_base64() {
            assert_eq!(super::encode(b"anna:pw"), "YW5uYTpwdw==");
            assert_eq!(super::encode(b"abc"), "YWJj");
            assert_eq!(super::encode(b"ab"), "YWI=");
        }
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn query_values_are_escaped() {
        assert_eq!(super::q("Plan Q1 & Q2.docx"), "Plan%20Q1%20%26%20Q2.docx");
        assert_eq!(super::q("Grüße.txt"), "Gr%C3%BC%C3%9Fe.txt");
    }
}
