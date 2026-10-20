//! The console's file browser.
//!
//! Each request asks the host once where its root lives and whether the caller may view
//! it, then lists, describes, or serves the entry under that root. The root ID stays
//! opaque here, only the host reads it.

use std::cmp::Ordering;
use std::collections::BinaryHeap;
use std::fs::{self, Metadata};
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use std::time::SystemTime;

use axum::Router;
use axum::body::Body;
use axum::extract::{Path as Captured, Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use ceres_config::FileExclusion;
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use tower::ServiceExt;
use tower_http::services::ServeFile;

use crate::api::dispatch::Dispatch;
use crate::app::AppState;
use crate::auth::Gate;
use crate::error::ApiError;
use crate::host::{Answer, HostError};

/// Most entries one listing returns, the rest reached through `?after`.
pub(crate) const LISTING_CAP: usize = 10_000;

/// Register the file browser's routes, beside the host-dispatched `/api/files`.
pub(crate) fn register(router: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    router
        .route("/api/files/{root}", get(root_entry))
        .route("/api/files/{root}/{*path}", get(entry))
}

async fn root_entry(
    State(state): State<Arc<AppState>>,
    Captured(root): Captured<String>,
    request: Request,
) -> Result<Response, ApiError> {
    respond(&state, root, String::new(), request).await
}

async fn entry(
    State(state): State<Arc<AppState>>,
    Captured((root, path)): Captured<(String, String)>,
    request: Request,
) -> Result<Response, ApiError> {
    respond(&state, root, path, request).await
}

/// Where a root lives, as the host resolved it for this caller.
#[derive(Deserialize)]
struct ResolvedRoot {
    path: PathBuf,
    exclude: Vec<String>,
}

/// What a request asks of the entry its path names.
#[derive(Default)]
struct FileQuery {
    hidden: bool,
    after: Option<String>,
    stat: bool,
    download: bool,
}

impl FileQuery {
    fn parse(query: Option<&str>) -> Self {
        let mut parsed = Self::default();
        for (name, value) in crate::api::query_pairs(query.map(str::to_string)) {
            let set = value != "false";
            match name.as_str() {
                "hidden" => parsed.hidden = set,
                "stat" => parsed.stat = set,
                "download" => parsed.download = set,
                "after" => parsed.after = Some(value),
                _ => {}
            }
        }

        parsed
    }
}

/// What an entry is, as the listing reports it.
#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "lowercase")]
enum EntryKind {
    File,
    Directory,
    /// A special file, a symlink leaving the root, or a name that is not UTF-8, none of
    /// which the browser opens.
    Other,
}

/// One entry of a listing, or the answer to `?stat`.
#[derive(Serialize)]
struct FileEntry {
    name: String,
    kind: EntryKind,
    /// Length in bytes, `None` for anything but a file.
    size: Option<u64>,
    /// Last modification as RFC 3339 with millisecond precision.
    modified: Option<String>,
}

impl FileEntry {
    fn new(name: String, kind: EntryKind, metadata: Option<&Metadata>) -> Self {
        let size = match kind {
            EntryKind::File => metadata.map(Metadata::len),
            EntryKind::Directory | EntryKind::Other => None,
        };
        let modified =
            metadata
                .and_then(|metadata| metadata.modified().ok())
                .map(|modified: SystemTime| {
                    DateTime::<Utc>::from(modified).to_rfc3339_opts(SecondsFormat::Millis, true)
                });

        Self {
            name,
            kind,
            size,
            modified,
        }
    }
}

#[derive(Serialize)]
struct FileListing {
    entries: Vec<FileEntry>,
    /// Whether entries past the last one returned exist.
    truncated: bool,
}

/// What the blocking half found at the requested path.
enum Found {
    Listing(FileListing),
    Stat(FileEntry),
    File { path: PathBuf, name: String },
}

/// A root opened for one request, its canonical path and exclusions.
struct OpenRoot {
    canonical: PathBuf,
    exclusion: FileExclusion,
}

impl OpenRoot {
    fn open(resolved: ResolvedRoot) -> Result<Self, ApiError> {
        let exclusion = FileExclusion::new(&resolved.exclude)
            .map_err(|error| HostError::Internal(format!("invalid `exclude` pattern: {error}")))?;
        let canonical = fs::canonicalize(&resolved.path).map_err(|_| ApiError::not_found())?;
        Ok(Self {
            canonical,
            exclusion,
        })
    }

    /// The `/`-joined path of `canonical` under the root, `None` when it lies outside.
    fn relative(&self, canonical: &Path) -> Option<String> {
        let relative = canonical.strip_prefix(&self.canonical).ok()?;
        let names: Vec<_> = relative
            .components()
            .map(|component| component.as_os_str().to_string_lossy())
            .collect();
        Some(names.join("/"))
    }

    /// Canonicalize `path`, `None` when it is missing, leaves the root, or is excluded.
    fn admit(&self, path: &Path) -> Option<PathBuf> {
        let canonical = fs::canonicalize(path).ok()?;
        let relative = self.relative(&canonical)?;
        (!self.exclusion.excludes(&relative)).then_some(canonical)
    }

    /// Find what `names`, each one validated, name under the root.
    fn find(&self, names: &[&str], query: &FileQuery) -> Result<Found, ApiError> {
        if self.exclusion.excludes(&names.join("/")) {
            return Err(ApiError::not_found());
        }

        let requested = names
            .iter()
            .fold(self.canonical.clone(), |path, name| path.join(name));
        let canonical = self.admit(&requested).ok_or_else(ApiError::not_found)?;
        let metadata = fs::metadata(&canonical).map_err(|_| ApiError::not_found())?;
        let name = names.last().copied().unwrap_or_default().to_string();

        if query.stat {
            return Ok(Found::Stat(FileEntry::new(
                name,
                kind_of(&metadata),
                Some(&metadata),
            )));
        }

        if metadata.is_dir() {
            if query.download {
                return Err(ApiError::http(StatusCode::BAD_REQUEST));
            }

            return self.list(&canonical, query).map(Found::Listing);
        }

        if metadata.is_file() {
            return Ok(Found::File {
                path: canonical,
                name,
            });
        }

        Err(ApiError::not_found())
    }

    /// List `directory`, sorted by name, at most [`LISTING_CAP`] entries after `query.after`.
    ///
    /// Reading the directory stays O(n) in its entries, the heap keeps only the first
    /// [`LISTING_CAP`] plus one names, and only those kept are stat'ed.
    fn list(&self, directory: &Path, query: &FileQuery) -> Result<FileListing, ApiError> {
        let relative = self.relative(directory).unwrap_or_default();
        let prefix = if relative.is_empty() {
            String::new()
        } else {
            format!("{relative}/")
        };

        let reader = fs::read_dir(directory).map_err(|_| ApiError::not_found())?;
        let mut kept = BinaryHeap::<Candidate>::new();
        for entry in reader.flatten() {
            let os_name = entry.file_name();
            let (name, unicode) = match os_name.to_str() {
                Some(name) => (name.to_string(), true),
                None => (os_name.to_string_lossy().into_owned(), false),
            };
            if (!query.hidden && name.starts_with('.'))
                || query.after.as_ref().is_some_and(|after| name <= *after)
                || self.exclusion.excludes(&format!("{prefix}{name}"))
            {
                continue;
            }

            kept.push(Candidate {
                name,
                path: entry.path(),
                unicode,
            });
            if kept.len() > LISTING_CAP + 1 {
                kept.pop();
            }
        }

        let mut candidates = kept.into_sorted_vec();
        let truncated = candidates.len() > LISTING_CAP;
        candidates.truncate(LISTING_CAP);

        let entries = candidates
            .into_iter()
            .filter_map(|candidate| self.describe(candidate))
            .collect();
        Ok(FileListing { entries, truncated })
    }

    /// Describe one listed entry, `None` for a symlink into an excluded path.
    fn describe(&self, candidate: Candidate) -> Option<FileEntry> {
        if !candidate.unicode {
            return Some(FileEntry::new(candidate.name, EntryKind::Other, None));
        }

        let Ok(metadata) = fs::symlink_metadata(&candidate.path) else {
            return Some(FileEntry::new(candidate.name, EntryKind::Other, None));
        };
        if !metadata.file_type().is_symlink() {
            return Some(FileEntry::new(
                candidate.name,
                kind_of(&metadata),
                Some(&metadata),
            ));
        }

        // A symlink takes its target's kind only while the target stays inside the root.
        let Ok(canonical) = fs::canonicalize(&candidate.path) else {
            return Some(FileEntry::new(
                candidate.name,
                EntryKind::Other,
                Some(&metadata),
            ));
        };
        let Some(relative) = self.relative(&canonical) else {
            return Some(FileEntry::new(
                candidate.name,
                EntryKind::Other,
                Some(&metadata),
            ));
        };
        if self.exclusion.excludes(&relative) {
            return None;
        }

        let target = fs::metadata(&canonical).ok()?;
        Some(FileEntry::new(
            candidate.name,
            kind_of(&target),
            Some(&target),
        ))
    }
}

/// One entry a listing may keep, ordered by name alone.
struct Candidate {
    name: String,
    path: PathBuf,
    unicode: bool,
}

impl PartialEq for Candidate {
    fn eq(&self, other: &Self) -> bool {
        self.name == other.name
    }
}

impl Eq for Candidate {}

impl PartialOrd for Candidate {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Candidate {
    fn cmp(&self, other: &Self) -> Ordering {
        self.name.cmp(&other.name)
    }
}

fn kind_of(metadata: &Metadata) -> EntryKind {
    if metadata.is_file() {
        EntryKind::File
    } else if metadata.is_dir() {
        EntryKind::Directory
    } else {
        EntryKind::Other
    }
}

/// Split a captured path into its names, refusing any that could leave the root.
fn split_path(path: &str) -> Result<Vec<&str>, ApiError> {
    if path.is_empty() {
        return Ok(Vec::new());
    }

    path.split('/')
        .map(|name| {
            let mut components = Path::new(name).components();
            let normal = matches!(components.next(), Some(Component::Normal(only)) if only == name)
                && components.next().is_none()
                && !name.contains(['\0'])
                && !name.chars().any(std::path::is_separator);
            if normal {
                Ok(name)
            } else {
                Err(ApiError::http(StatusCode::BAD_REQUEST))
            }
        })
        .collect()
}

/// The `Content-Disposition` value that saves a download under `name`.
fn attachment(name: &str) -> HeaderValue {
    let fallback: String = name
        .chars()
        .map(|character| {
            if character == ' '
                || (character.is_ascii_graphic() && !matches!(character, '"' | '\\'))
            {
                character
            } else {
                '_'
            }
        })
        .collect();
    let encoded = percent_encoding::utf8_percent_encode(name, percent_encoding::NON_ALPHANUMERIC);
    HeaderValue::from_str(&format!(
        "attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
    ))
    .unwrap_or_else(|_| HeaderValue::from_static("attachment"))
}

async fn respond(
    state: &AppState,
    root: String,
    path: String,
    request: Request,
) -> Result<Response, ApiError> {
    let query = FileQuery::parse(request.uri().query());
    let Answer::Payload(payload) =
        Dispatch::lookup(Gate::Authenticated, "files.resolve", [("root", root)])
            .answer(state, request.headers(), None)
            .await?
    else {
        return Err(HostError::Internal("files.resolve answered without a payload".into()).into());
    };
    let resolved: ResolvedRoot = serde_json::from_str(&payload)
        .map_err(|error| HostError::Internal(format!("files.resolve answered {error}")))?;

    let download = query.download;
    let found = tokio::task::spawn_blocking(move || {
        let names = split_path(&path)?;
        OpenRoot::open(resolved)?.find(&names, &query)
    })
    .await
    .map_err(|error| HostError::Internal(error.to_string()))??;

    match found {
        Found::Listing(listing) => Ok(json(&listing)),
        Found::Stat(entry) => Ok(json(&entry)),
        Found::File { path, name } => {
            // Reopening by path lets a symlink swapped in since the canonical check escape the
            // root. Writes in the next stage must serve from a handle whose (dev, ino) it verified.
            let Ok(mut response) = ServeFile::new(path).oneshot(request).await;
            // A served HTML or SVG file opened as a page runs in an opaque origin, so its scripts
            // never reach the console's session.
            let headers = response.headers_mut();
            headers.insert(
                header::CONTENT_SECURITY_POLICY,
                HeaderValue::from_static("sandbox"),
            );
            headers.insert(
                header::X_CONTENT_TYPE_OPTIONS,
                HeaderValue::from_static("nosniff"),
            );
            if download {
                headers.insert(header::CONTENT_DISPOSITION, attachment(&name));
            }

            Ok(response.map(Body::new))
        }
    }
}

fn json(value: &impl Serialize) -> Response {
    match serde_json::to_string(value) {
        Ok(body) => crate::app::json_response(body),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}

#[cfg(test)]
mod tests {
    use axum::http::Request as HttpRequest;
    use http_body_util::BodyExt;
    use serde_json::{Value, json};
    use tempfile::TempDir;

    use super::*;
    use crate::app::{AppConfig, build_router};
    use crate::host::{Host, UserRecord};
    use crate::layers::apply_compression;

    /// A host serving one root, `files`, over a temporary directory.
    struct FileHost {
        directory: TempDir,
        exclude: Vec<&'static str>,
    }

    #[async_trait::async_trait]
    impl Host for FileHost {
        async fn user(&self, _: uuid::Uuid) -> Result<Option<UserRecord>, HostError> {
            Ok(None)
        }

        async fn verify_login(
            &self,
            _: String,
            _: String,
        ) -> Result<Option<UserRecord>, HostError> {
            Ok(None)
        }

        async fn change_password(
            &self,
            _: uuid::Uuid,
            _: String,
            _: String,
        ) -> Result<Option<UserRecord>, HostError> {
            Ok(None)
        }

        async fn operate(&self, operation: &str, arguments: Value) -> Result<Answer, HostError> {
            assert_eq!(operation, "files.resolve");
            if arguments["path"]["root"] != "files" {
                return Err(HostError::Typed {
                    status: 404,
                    envelope: "{}".into(),
                });
            }

            let root =
                json!({"path": self.directory.path(), "level": "view", "exclude": self.exclude});
            Ok(Answer::Payload(root.to_string()))
        }
    }

    /// A root holding `files`, each a path and its contents, under `exclude`.
    fn root(files: &[(&str, &str)], exclude: &[&'static str]) -> FileHost {
        let directory = TempDir::new().unwrap();
        for (path, contents) in files {
            let path = directory.path().join(path);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, contents).unwrap();
        }

        FileHost {
            directory,
            exclude: exclude.to_vec(),
        }
    }

    impl FileHost {
        #[cfg(unix)]
        fn link(&self, target: &Path, link: &str) {
            std::os::unix::fs::symlink(target, self.directory.path().join(link)).unwrap();
        }

        async fn get(self: &Arc<Self>, uri: &str) -> Response {
            self.request(HttpRequest::get(uri)).await
        }

        /// Answers `request` through the router and the default compression layers, as served.
        async fn request(self: &Arc<Self>, request: axum::http::request::Builder) -> Response {
            let app = build_router(AppConfig {
                console: None,
                cli_token: None,
                auth: None,
                host: Arc::clone(self) as Arc<dyn Host>,
                version: "0.0.0".to_string(),
                authority: None,
                webrtc: None,
            });
            apply_compression(app, None)
                .oneshot(request.body(Body::empty()).unwrap())
                .await
                .unwrap()
        }

        async fn json(self: &Arc<Self>, uri: &str) -> Value {
            let response = self.get(uri).await;
            assert_eq!(response.status(), StatusCode::OK, "{uri}");
            serde_json::from_slice(&body(response).await).unwrap()
        }

        /// The names a listing at `uri` returns, in order.
        async fn names(self: &Arc<Self>, uri: &str) -> Vec<String> {
            let listing = self.json(uri).await;
            listing["entries"]
                .as_array()
                .unwrap()
                .iter()
                .map(|entry| entry["name"].as_str().unwrap().to_string())
                .collect()
        }
    }

    async fn body(response: Response) -> Vec<u8> {
        response
            .into_body()
            .collect()
            .await
            .unwrap()
            .to_bytes()
            .to_vec()
    }

    #[tokio::test]
    async fn a_listing_is_sorted_and_omits_dot_entries_unless_asked() {
        let host = Arc::new(root(&[("b.txt", "abc"), ("a/c.txt", ""), (".d", "")], &[]));
        let listing = host.json("/api/files/files").await;
        assert_eq!(listing["truncated"], false);
        assert_eq!(listing["entries"][0]["name"], "a");
        assert_eq!(listing["entries"][0]["kind"], "directory");
        assert_eq!(listing["entries"][0]["size"], Value::Null);
        assert_eq!(listing["entries"][1]["kind"], "file");
        assert_eq!(listing["entries"][1]["size"], 3);
        assert!(
            listing["entries"][1]["modified"]
                .as_str()
                .unwrap()
                .ends_with('Z')
        );

        assert_eq!(
            host.names("/api/files/files?hidden=true").await,
            [".d", "a", "b.txt"]
        );
        assert_eq!(host.names("/api/files/files/a").await, ["c.txt"]);
        assert_eq!(host.names("/api/files/files?after=a").await, ["b.txt"]);
    }

    #[tokio::test]
    async fn a_listing_past_the_cap_is_truncated() {
        let host = Arc::new(root(&[], &[]));
        for index in 0..=LISTING_CAP {
            fs::write(host.directory.path().join(format!("{index:05}")), "").unwrap();
        }

        let listing = host.json("/api/files/files").await;
        assert_eq!(listing["truncated"], true);
        assert_eq!(listing["entries"].as_array().unwrap().len(), LISTING_CAP);
        assert_eq!(host.names("/api/files/files?after=09999").await, ["10000"]);
    }

    #[tokio::test]
    async fn a_file_serves_its_bytes_ranges_and_downloads() {
        let host = Arc::new(root(&[("a/b c.txt", "abcd")], &[]));
        let response = host.get("/api/files/files/a/b%20c.txt").await;
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers()[header::CONTENT_TYPE], "text/plain");
        assert_eq!(
            response.headers()[header::CONTENT_SECURITY_POLICY],
            "sandbox"
        );
        assert_eq!(
            response.headers()[header::X_CONTENT_TYPE_OPTIONS],
            "nosniff"
        );
        assert_eq!(body(response).await, b"abcd");

        let ranged = host
            .request(
                HttpRequest::get("/api/files/files/a/b%20c.txt").header(header::RANGE, "bytes=1-2"),
            )
            .await;
        assert_eq!(ranged.status(), StatusCode::PARTIAL_CONTENT);
        assert_eq!(body(ranged).await, b"bc");

        let download = host.get("/api/files/files/a/b%20c.txt?download").await;
        assert_eq!(
            download.headers()[header::CONTENT_DISPOSITION],
            "attachment; filename=\"b c.txt\"; filename*=UTF-8''b%20c%2Etxt"
        );
        assert_eq!(
            host.get("/api/files/files/a?download").await.status(),
            StatusCode::BAD_REQUEST
        );
    }

    #[tokio::test]
    async fn a_file_unchanged_since_its_etag_answers_not_modified() {
        let host = Arc::new(root(&[("a.txt", "abcd")], &[]));
        let response = host.get("/api/files/files/a.txt").await;
        let etag = response.headers()[header::ETAG].clone();

        let cached = host
            .request(HttpRequest::get("/api/files/files/a.txt").header(header::IF_NONE_MATCH, etag))
            .await;
        assert_eq!(cached.status(), StatusCode::NOT_MODIFIED);
        assert!(body(cached).await.is_empty());
    }

    #[tokio::test]
    async fn a_whole_text_file_compresses_and_a_range_of_it_does_not() {
        let host = Arc::new(root(&[("a.csv", &"x,y\n".repeat(1000))], &[]));
        let whole = host
            .request(
                HttpRequest::get("/api/files/files/a.csv").header(header::ACCEPT_ENCODING, "gzip"),
            )
            .await;
        assert_eq!(whole.headers()[header::CONTENT_ENCODING], "gzip");

        let ranged = host
            .request(
                HttpRequest::get("/api/files/files/a.csv")
                    .header(header::ACCEPT_ENCODING, "gzip")
                    .header(header::RANGE, "bytes=0-3"),
            )
            .await;
        assert_eq!(ranged.status(), StatusCode::PARTIAL_CONTENT);
        assert!(ranged.headers().get(header::CONTENT_ENCODING).is_none());
        assert_eq!(body(ranged).await, b"x,y\n");
    }

    #[tokio::test]
    async fn stat_describes_an_entry_and_the_root() {
        let host = Arc::new(root(&[("a/b", "abc")], &[]));
        let stat = host.json("/api/files/files/a/b?stat").await;
        assert_eq!(
            (&stat["name"], &stat["kind"], &stat["size"]),
            (&json!("b"), &json!("file"), &json!(3))
        );

        let stat = host.json("/api/files/files?stat").await;
        assert_eq!(
            (&stat["name"], &stat["kind"]),
            (&json!(""), &json!("directory"))
        );
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn an_excluded_entry_is_never_listed_or_served() {
        let host = Arc::new(root(
            &[("a/.venv/x", "abc"), ("data/raw/y", ""), ("z", "")],
            &[".venv", "/data/raw"],
        ));
        host.link(&host.directory.path().join("data/raw/y"), "link");

        assert_eq!(
            host.names("/api/files/files?hidden=true").await,
            ["a", "data", "z"]
        );
        assert_eq!(
            host.names("/api/files/files/a?hidden=true").await,
            Vec::<String>::new()
        );
        assert_eq!(
            host.names("/api/files/files/data").await,
            Vec::<String>::new()
        );
        for path in ["a/.venv", "a/.venv/x", "data/raw/y", "link", "missing"] {
            let response = host.get(&format!("/api/files/files/{path}")).await;
            assert_eq!(response.status(), StatusCode::NOT_FOUND, "{path}");
        }
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn a_symlink_leaving_the_root_is_listed_as_other_and_never_served() {
        let outside = TempDir::new().unwrap();
        fs::write(outside.path().join("secret"), "abc").unwrap();
        let host = Arc::new(root(&[("a", "abc")], &[]));
        host.link(&outside.path().join("secret"), "out");
        host.link(&host.directory.path().join("a"), "in");

        let listing = host.json("/api/files/files").await;
        let kinds: Vec<_> = listing["entries"]
            .as_array()
            .unwrap()
            .iter()
            .map(|entry| entry["kind"].clone())
            .collect();
        assert_eq!(kinds, [json!("file"), json!("file"), json!("other")]);
        assert_eq!(
            host.get("/api/files/files/out").await.status(),
            StatusCode::NOT_FOUND
        );
        assert_eq!(body(host.get("/api/files/files/in").await).await, b"abc");
    }

    #[tokio::test]
    async fn an_unknown_root_answers_what_the_host_does() {
        let host = Arc::new(root(&[], &[]));
        assert_eq!(
            host.get("/api/files/other").await.status(),
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            host.get("/api/files/files/%2E%2E").await.status(),
            StatusCode::BAD_REQUEST
        );
    }

    #[test]
    fn a_path_that_could_leave_the_root_is_refused() {
        for path in ["..", "a/../b", ".", "a//b", "/a", "a/", "a\0b"] {
            assert!(split_path(path).is_err(), "{path:?}");
        }

        assert_eq!(split_path("a/b c/.d").unwrap(), ["a", "b c", ".d"]);
        assert!(split_path("").unwrap().is_empty());
    }

    #[test]
    fn an_attachment_falls_back_to_ascii() {
        assert_eq!(
            attachment("a \"b\" é.txt"),
            "attachment; filename=\"a _b_ _.txt\"; filename*=UTF-8''a%20%22b%22%20%C3%A9%2Etxt"
        );
    }
}
