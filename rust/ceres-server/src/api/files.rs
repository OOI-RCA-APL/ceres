//! The console's file browser.
//!
//! Each request asks the host once where its root lives and what the caller may do there,
//! then lists, describes, serves, or changes the entry under that root. The root ID stays
//! opaque here, only the host reads it.

use std::cmp::Ordering;
use std::collections::BinaryHeap;
use std::fs::{self, File, Metadata};
use std::future::{Ready, ready};
use std::io::{self, ErrorKind};
use std::path::{Component, Path, PathBuf};
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::{Duration, SystemTime};

use axum::Router;
use axum::body::Body;
use axum::extract::{Path as Captured, Request, State};
use axum::http::{HeaderMap, HeaderValue, Method, StatusCode, Uri, header};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use ceres_config::FileExclusion;
use chrono::{DateTime, SecondsFormat, Utc};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncRead, AsyncSeek, AsyncWriteExt, ReadBuf};
use tower::ServiceExt;
use tower_http::services::ServeDir;
use tower_http::services::fs::{Backend, File as BackendFile};
use uuid::Uuid;

use crate::api::dispatch::Dispatch;
use crate::app::AppState;
use crate::auth::Gate;
use crate::error::ApiError;
use crate::host::{Answer, HostError};

/// Most entries one listing returns, the rest reached through `?after`.
pub(crate) const LISTING_CAP: usize = 10_000;

/// How long an upload's part may go unwritten before a listing removes it. An upload in
/// progress writes continuously, so its part never ages this far.
const PART_LIFETIME: Duration = Duration::from_secs(60 * 60);

/// Largest `PATCH` body read, far above any path the filesystem accepts.
const RENAME_BODY_LIMIT: usize = 64 * 1024;

/// Register the file browser's routes, beside the host-dispatched `/api/files`.
pub(crate) fn register(router: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    router
        .route(
            "/api/files/{root}",
            get(root_entry)
                .put(root_entry)
                .patch(root_entry)
                .delete(root_entry),
        )
        .route(
            "/api/files/{root}/{*path}",
            get(entry).put(entry).patch(entry).delete(entry),
        )
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

/// Where a root lives and what the caller may do there, as the host resolved it.
#[derive(Deserialize)]
struct ResolvedRoot {
    path: PathBuf,
    writable: bool,
    exclude: Vec<String>,
    max_upload: Option<u64>,
}

/// What a request asks of the entry its path names.
#[derive(Default)]
struct FileQuery {
    hidden: bool,
    after: Option<String>,
    stat: bool,
    download: bool,
    directory: bool,
    recursive: bool,
    overwrite: bool,
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
                "directory" => parsed.directory = set,
                "recursive" => parsed.recursive = set,
                "overwrite" => parsed.overwrite = set,
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
    File(VerifiedFile, String),
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
    fn find(&self, names: &[String], query: &FileQuery) -> Result<Found, ApiError> {
        if self.exclusion.excludes(&names.join("/")) {
            return Err(ApiError::not_found());
        }

        let requested = names
            .iter()
            .fold(self.canonical.clone(), |path, name| path.join(name));
        let canonical = self.admit(&requested).ok_or_else(ApiError::not_found)?;
        let metadata = fs::metadata(&canonical).map_err(|_| ApiError::not_found())?;
        let name = names.last().cloned().unwrap_or_default();

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
            let file = VerifiedFile::open(canonical, &metadata).ok_or_else(ApiError::not_found)?;
            return Ok(Found::File(file, name));
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
            if (unicode && is_part(&name) && sweep_if_stale(&entry))
                || (!query.hidden && name.starts_with('.'))
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

    /// Find the entry a write names, under a parent directory admitted like a read.
    ///
    /// The entry itself is never followed, so a write acts on a symlink and never on what it
    /// points at.
    fn target(&self, names: &[String]) -> Result<WriteTarget, ApiError> {
        let Some((name, parents)) = names.split_last() else {
            return Err(ApiError::http(StatusCode::BAD_REQUEST));
        };
        if self.exclusion.excludes(&names.join("/")) {
            return Err(ApiError::not_found());
        }

        let requested = parents
            .iter()
            .fold(self.canonical.clone(), |path, name| path.join(name));
        let parent = self.admit(&requested).ok_or_else(ApiError::not_found)?;
        if !fs::metadata(&parent).is_ok_and(|metadata| metadata.is_dir()) {
            return Err(ApiError::not_found());
        }

        let relative = match self.relative(&parent).unwrap_or_default() {
            above if above.is_empty() => name.clone(),
            above => format!("{above}/{name}"),
        };
        if self.exclusion.excludes(&relative) {
            return Err(ApiError::not_found());
        }

        Ok(WriteTarget {
            parent,
            name: name.clone(),
            relative,
        })
    }

    /// Whether any entry below `directory`, at `relative` under the root, is excluded.
    ///
    /// Costs a walk of the whole subtree, the same walk the delete or move it guards pays.
    fn holds_excluded(&self, directory: &Path, relative: &str) -> io::Result<bool> {
        for entry in fs::read_dir(directory)? {
            let entry = entry?;
            let path = format!("{relative}/{}", entry.file_name().to_string_lossy());
            if self.exclusion.excludes(&path)
                || (entry.file_type()?.is_dir() && self.holds_excluded(&entry.path(), &path)?)
            {
                return Ok(true);
            }
        }

        Ok(false)
    }

    /// Refuse to delete or move the directory `target` names when it holds an excluded
    /// entry, which no write may reach.
    fn refuse_excluded_below(
        &self,
        target: &WriteTarget,
        metadata: &Metadata,
    ) -> Result<(), ApiError> {
        if metadata.is_dir()
            && self
                .holds_excluded(&target.path(), &target.relative)
                .map_err(write_error)?
        {
            return Err(ApiError::http(StatusCode::CONFLICT));
        }

        Ok(())
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
fn split_path(path: &str) -> Result<Vec<String>, ApiError> {
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
                Ok(name.to_string())
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

/// A file the read path opened and checked against the walk, which `ServeDir` serves in
/// place of reopening it by path.
#[derive(Clone)]
struct VerifiedFile {
    path: PathBuf,
    metadata: Metadata,
    handle: Arc<Mutex<Option<File>>>,
}

impl VerifiedFile {
    /// Open the regular file the walk found at `canonical`, `None` when another file took
    /// its place since.
    fn open(canonical: PathBuf, walked: &Metadata) -> Option<Self> {
        let file = open_without_following(&canonical).ok()?;
        let metadata = file.metadata().ok()?;
        let same = metadata.is_file() && same_file(walked, &metadata).unwrap_or(true);
        same.then(|| Self {
            path: canonical,
            metadata,
            handle: Arc::new(Mutex::new(Some(file))),
        })
    }
}

/// Open `path` for reading, failing when its last component is a symlink.
#[cfg(unix)]
fn open_without_following(path: &Path) -> io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;

    fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
}

#[cfg(not(unix))]
fn open_without_following(path: &Path) -> io::Result<File> {
    File::open(path)
}

/// Whether `a` and `b` describe the same file, `None` where the platform cannot tell.
#[cfg(unix)]
fn same_file(a: &Metadata, b: &Metadata) -> Option<bool> {
    use std::os::unix::fs::MetadataExt;

    Some(a.dev() == b.dev() && a.ino() == b.ino())
}

#[cfg(not(unix))]
fn same_file(_: &Metadata, _: &Metadata) -> Option<bool> {
    None
}

impl Backend for VerifiedFile {
    type File = VerifiedHandle;
    type Metadata = Metadata;
    type OpenFuture = Ready<io::Result<VerifiedHandle>>;
    type MetadataFuture = Ready<io::Result<Metadata>>;

    /// Hand over the verified handle, once, and only for its own path, so a probe of any
    /// other path fails closed.
    fn open(&self, path: PathBuf) -> Self::OpenFuture {
        let file = (path == self.path)
            .then(|| self.handle.lock().ok()?.take())
            .flatten();
        ready(
            file.map(|file| VerifiedHandle {
                file: tokio::fs::File::from_std(file),
                metadata: self.metadata.clone(),
            })
            .ok_or_else(|| ErrorKind::NotFound.into()),
        )
    }

    fn metadata(&self, path: PathBuf) -> Self::MetadataFuture {
        ready(if path == self.path {
            Ok(self.metadata.clone())
        } else {
            Err(ErrorKind::NotFound.into())
        })
    }
}

/// The opened half of [`VerifiedFile`], read and seeked by `ServeDir`.
struct VerifiedHandle {
    file: tokio::fs::File,
    metadata: Metadata,
}

impl AsyncRead for VerifiedHandle {
    fn poll_read(
        mut self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(&mut self.file).poll_read(context, buffer)
    }
}

impl AsyncSeek for VerifiedHandle {
    fn start_seek(mut self: Pin<&mut Self>, position: io::SeekFrom) -> io::Result<()> {
        Pin::new(&mut self.file).start_seek(position)
    }

    fn poll_complete(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<io::Result<u64>> {
        Pin::new(&mut self.file).poll_complete(context)
    }
}

impl BackendFile for VerifiedHandle {
    type Metadata = Metadata;
    type MetadataFuture<'a> = Ready<io::Result<Metadata>>;

    fn metadata(&self) -> Self::MetadataFuture<'_> {
        ready(Ok(self.metadata.clone()))
    }
}

/// The entry a write names, in a parent directory the walk admitted.
struct WriteTarget {
    /// Canonical path of the directory holding the entry.
    parent: PathBuf,
    name: String,
    /// The entry's `/`-joined path under the root.
    relative: String,
}

impl WriteTarget {
    fn path(&self) -> PathBuf {
        self.parent.join(&self.name)
    }

    /// What sits at the entry itself, a symlink unfollowed, `None` when nothing does.
    fn existing(&self) -> Result<Option<Metadata>, ApiError> {
        match fs::symlink_metadata(self.path()) {
            Ok(metadata) => Ok(Some(metadata)),
            Err(error) if error.kind() == ErrorKind::NotFound => Ok(None),
            Err(error) => Err(write_error(error)),
        }
    }
}

/// Whether `name` has the shape of an upload's part, `.<name>.<uuid>.part`.
fn is_part(name: &str) -> bool {
    let Some(stem) = name
        .strip_prefix('.')
        .and_then(|name| name.strip_suffix(".part"))
    else {
        return false;
    };

    stem.rsplit_once('.').is_some_and(|(target, id)| {
        !target.is_empty() && id.len() == 36 && Uuid::try_parse(id).is_ok()
    })
}

/// Remove `entry` when it is a part whose upload stopped over [`PART_LIFETIME`] ago.
fn sweep_if_stale(entry: &fs::DirEntry) -> bool {
    let stale = entry
        .metadata()
        .ok()
        .filter(Metadata::is_file)
        .and_then(|metadata| metadata.modified().ok())
        .and_then(|modified| modified.elapsed().ok())
        .is_some_and(|age| age > PART_LIFETIME);
    stale && fs::remove_file(entry.path()).is_ok()
}

/// The file an upload writes before it takes the target's name.
///
/// [`PartFile::discard`] removes it once the upload ends, and dropping it removes it too, for
/// an upload whose client went away mid-body.
struct PartFile {
    path: Option<PathBuf>,
}

impl PartFile {
    /// Move the part over `target`, `true` when nothing stood there before.
    fn commit(
        &mut self,
        target: &WriteTarget,
        conditions: &UploadConditions,
    ) -> Result<bool, ApiError> {
        let Some(part) = self.path.clone() else {
            return Err(ApiError::http(StatusCode::CONFLICT));
        };
        let existing = target.existing()?;
        conditions.check(existing.as_ref())?;

        let path = target.path();
        if conditions.create_only {
            // A link fails when the name exists, so a racing upload cannot be replaced.
            match fs::hard_link(&part, &path) {
                Ok(()) => return Ok(true),
                Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                    return Err(ApiError::http(StatusCode::PRECONDITION_FAILED));
                }
                // A filesystem without hard links falls back to the check above.
                Err(_) => {}
            }
        }

        fs::rename(&part, &path).map_err(|error| {
            if error.kind() == ErrorKind::NotFound {
                expired()
            } else {
                write_error(error)
            }
        })?;
        self.path = None;
        Ok(existing.is_none())
    }

    /// Remove the part unless [`PartFile::commit`] moved it into place.
    fn discard(mut self) {
        if let Some(path) = self.path.take() {
            let _ = fs::remove_file(path);
        }
    }
}

impl Drop for PartFile {
    fn drop(&mut self) {
        let Some(path) = self.path.take() else {
            return;
        };

        let remove = move || {
            let _ = fs::remove_file(path);
        };
        match tokio::runtime::Handle::try_current() {
            Ok(runtime) => drop(runtime.spawn_blocking(remove)),
            Err(_) => remove(),
        }
    }
}

/// The conflict an upload answers when its part was swept before it finished.
fn expired() -> ApiError {
    let mut error = ApiError::http(StatusCode::CONFLICT);
    error.fields.insert(
        "message".to_string(),
        "The upload expired before it finished.".into(),
    );
    error
}

/// The preconditions an upload carries, `If-None-Match: *` and `If-Match`.
struct UploadConditions {
    create_only: bool,
    if_match: Option<String>,
}

impl UploadConditions {
    fn parse(headers: &HeaderMap) -> Self {
        let text = |name| {
            headers
                .get(name)
                .and_then(|value: &HeaderValue| value.to_str().ok())
                .map(str::trim)
        };
        Self {
            create_only: text(header::IF_NONE_MATCH) == Some("*"),
            if_match: text(header::IF_MATCH).map(str::to_string),
        }
    }

    /// Refuse the upload unless the entry `existing` describes may take its bytes.
    fn check(&self, existing: Option<&Metadata>) -> Result<(), ApiError> {
        let Some(existing) = existing else {
            return match self.if_match {
                Some(_) => Err(ApiError::http(StatusCode::PRECONDITION_FAILED)),
                None => Ok(()),
            };
        };

        // A symlink stays a symlink, the upload never writes through it.
        if !existing.is_file() {
            return Err(ApiError::http(StatusCode::CONFLICT));
        }

        let matched = self.if_match.as_deref().is_none_or(|tags| {
            let current = etag(existing);
            tags.split(',')
                .map(str::trim)
                .any(|tag| tag == "*" || Some(tag) == current.as_deref())
        });
        if self.create_only || !matched {
            return Err(ApiError::http(StatusCode::PRECONDITION_FAILED));
        }

        Ok(())
    }
}

/// The ETag a read serves for the file `metadata` describes, which `If-Match` compares
/// against. It repeats the format of `tower_http`'s private `ETag::from_metadata` in
/// `services/fs/serve_dir/headers.rs`, and a test holds the two together.
fn etag(metadata: &Metadata) -> Option<String> {
    let since = metadata
        .modified()
        .ok()?
        .duration_since(SystemTime::UNIX_EPOCH)
        .ok()?;
    Some(format!(
        "\"{:x}.{:08x}-{:x}\"",
        since.as_secs(),
        since.subsec_nanos(),
        metadata.len()
    ))
}

/// The status a failed write answers for what the filesystem reported.
fn write_error(error: io::Error) -> ApiError {
    let status = match error.kind() {
        ErrorKind::NotFound => return ApiError::not_found(),
        ErrorKind::AlreadyExists
        | ErrorKind::DirectoryNotEmpty
        | ErrorKind::IsADirectory
        | ErrorKind::NotADirectory
        | ErrorKind::CrossesDevices => StatusCode::CONFLICT,
        ErrorKind::InvalidInput | ErrorKind::InvalidFilename => StatusCode::BAD_REQUEST,
        ErrorKind::StorageFull | ErrorKind::QuotaExceeded => StatusCode::INSUFFICIENT_STORAGE,
        ErrorKind::PermissionDenied | ErrorKind::ReadOnlyFilesystem => StatusCode::FORBIDDEN,
        _ => return HostError::Internal(error.to_string()).into(),
    };
    ApiError::http(status)
}

/// Run filesystem work on the blocking pool.
async fn blocking<T: Send + 'static>(
    work: impl FnOnce() -> Result<T, ApiError> + Send + 'static,
) -> Result<T, ApiError> {
    tokio::task::spawn_blocking(work)
        .await
        .map_err(|error| HostError::Internal(error.to_string()))?
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
    let names = split_path(&path)?;

    let method = request.method().clone();
    if method == Method::GET || method == Method::HEAD {
        return read(resolved, names, query, request).await;
    }

    if !resolved.writable {
        return Err(ApiError::not_permitted());
    }

    match method {
        Method::PUT if query.directory => create_directory(resolved, names).await,
        Method::PUT => upload(resolved, names, request).await,
        Method::PATCH => rename(resolved, names, query, request).await,
        Method::DELETE => delete(resolved, names, query).await,
        _ => Err(ApiError::http(StatusCode::METHOD_NOT_ALLOWED)),
    }
}

async fn read(
    resolved: ResolvedRoot,
    names: Vec<String>,
    query: FileQuery,
    request: Request,
) -> Result<Response, ApiError> {
    let download = query.download;
    let found = blocking(move || OpenRoot::open(resolved)?.find(&names, &query)).await?;

    match found {
        Found::Listing(listing) => Ok(json(&listing)),
        Found::Stat(entry) => Ok(json(&entry)),
        Found::File(file, name) => {
            // The handle closes a swap of the file itself for a symlink. A parent directory
            // swapped between the walk and the open still escapes, as writes do.
            let path = file.path.clone();
            let (mut parts, body) = request.into_parts();
            parts.uri = Uri::from_static("/");
            let Ok(mut response) = ServeDir::with_backend(&path, file)
                .append_index_html_on_directories(false)
                .oneshot(Request::from_parts(parts, body))
                .await;
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

/// Stream the request's body into a part beside the target, then move it into place.
async fn upload(
    resolved: ResolvedRoot,
    names: Vec<String>,
    request: Request,
) -> Result<Response, ApiError> {
    let limit = resolved.max_upload;
    let declared = request
        .headers()
        .get(header::CONTENT_LENGTH)
        .and_then(|value| value.to_str().ok()?.parse::<u64>().ok());
    if let (Some(limit), Some(declared)) = (limit, declared)
        && declared > limit
    {
        return Err(ApiError::http(StatusCode::PAYLOAD_TOO_LARGE));
    }

    let conditions = UploadConditions::parse(request.headers());
    let (target, part, file, conditions) = blocking(move || {
        let target = OpenRoot::open(resolved)?.target(&names)?;
        if is_part(&target.name) {
            return Err(ApiError::http(StatusCode::BAD_REQUEST));
        }

        conditions.check(target.existing()?.as_ref())?;
        let path = target
            .parent
            .join(format!(".{}.{}.part", target.name, Uuid::new_v4()));
        let file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .map_err(write_error)?;
        Ok((target, PartFile { path: Some(path) }, file, conditions))
    })
    .await?;

    let streamed = write_body(tokio::fs::File::from_std(file), request.into_body(), limit).await;
    let created = blocking(move || {
        let mut part = part;
        let created = streamed.and_then(|()| part.commit(&target, &conditions));
        part.discard();
        created
    })
    .await?;
    Ok(if created {
        StatusCode::CREATED
    } else {
        StatusCode::NO_CONTENT
    }
    .into_response())
}

/// Write `body` to `file` and sync it, refusing it past `limit` bytes.
async fn write_body(
    mut file: tokio::fs::File,
    body: Body,
    limit: Option<u64>,
) -> Result<(), ApiError> {
    let mut written = 0u64;
    let mut body = body.into_data_stream();
    while let Some(chunk) = body.next().await {
        let chunk = chunk.map_err(|_| ApiError::http(StatusCode::BAD_REQUEST))?;
        written += chunk.len() as u64;
        if limit.is_some_and(|limit| written > limit) {
            return Err(ApiError::http(StatusCode::PAYLOAD_TOO_LARGE));
        }

        file.write_all(&chunk).await.map_err(write_error)?;
    }

    // The files are the archive, so the bytes reach the disk before the name moves.
    file.flush().await.map_err(write_error)?;
    file.sync_all().await.map_err(write_error)
}

async fn create_directory(
    resolved: ResolvedRoot,
    names: Vec<String>,
) -> Result<Response, ApiError> {
    blocking(move || {
        let target = OpenRoot::open(resolved)?.target(&names)?;
        fs::create_dir(target.path()).map_err(write_error)?;
        Ok(StatusCode::CREATED.into_response())
    })
    .await
}

/// The body of a rename, the destination's path under the same root.
#[derive(Deserialize)]
struct RenameBody {
    to: String,
}

async fn rename(
    resolved: ResolvedRoot,
    names: Vec<String>,
    query: FileQuery,
    request: Request,
) -> Result<Response, ApiError> {
    let bad_request = || ApiError::http(StatusCode::BAD_REQUEST);
    let bytes = axum::body::to_bytes(request.into_body(), RENAME_BODY_LIMIT)
        .await
        .map_err(|_| bad_request())?;
    let body: RenameBody = serde_json::from_slice(&bytes).map_err(|_| bad_request())?;
    let destination = split_path(&body.to)?;

    blocking(move || {
        let root = OpenRoot::open(resolved)?;
        let source = root.target(&names)?;
        let destination = root.target(&destination)?;
        if is_part(&destination.name) {
            return Err(bad_request());
        }

        let moved = source.existing()?.ok_or_else(ApiError::not_found)?;
        if moved.is_dir() && destination.parent.starts_with(source.path()) {
            return Err(bad_request());
        }

        match destination.existing()? {
            // A rename that changes only the case of a name finds the source itself there.
            Some(existing) if same_file(&moved, &existing) == Some(true) => {}
            Some(existing) if existing.is_dir() || !query.overwrite => {
                return Err(ApiError::http(StatusCode::CONFLICT));
            }
            _ => {}
        }

        root.refuse_excluded_below(&source, &moved)?;
        fs::rename(source.path(), destination.path()).map_err(write_error)?;
        Ok(StatusCode::NO_CONTENT.into_response())
    })
    .await
}

async fn delete(
    resolved: ResolvedRoot,
    names: Vec<String>,
    query: FileQuery,
) -> Result<Response, ApiError> {
    blocking(move || {
        let root = OpenRoot::open(resolved)?;
        let target = root.target(&names)?;
        let existing = target.existing()?.ok_or_else(ApiError::not_found)?;
        let path = target.path();
        let removed = if !existing.is_dir() {
            fs::remove_file(path)
        } else if query.recursive {
            root.refuse_excluded_below(&target, &existing)?;
            // The standard library walks the tree without following a symlink swapped in.
            fs::remove_dir_all(path)
        } else {
            fs::remove_dir(path)
        };
        removed.map_err(write_error)?;
        Ok(StatusCode::NO_CONTENT.into_response())
    })
    .await
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
        writable: bool,
        max_upload: Option<u64>,
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

            let root = json!({
                "path": self.directory.path(),
                "level": "view",
                "writable": self.writable,
                "exclude": self.exclude,
                "max_upload": self.max_upload,
            });
            Ok(Answer::Payload(root.to_string()))
        }
    }

    /// A writable root holding `files`, each a path and its contents, under `exclude`.
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
            writable: true,
            max_upload: None,
        }
    }

    impl FileHost {
        fn path(&self, path: &str) -> PathBuf {
            self.directory.path().join(path)
        }

        fn contents(&self, path: &str) -> Option<String> {
            fs::read_to_string(self.path(path)).ok()
        }

        #[cfg(unix)]
        fn link(&self, target: &Path, link: &str) {
            std::os::unix::fs::symlink(target, self.path(link)).unwrap();
        }

        async fn get(self: &Arc<Self>, uri: &str) -> Response {
            self.request(HttpRequest::get(uri)).await
        }

        /// Answers `request` through the router and the default compression layers, as served.
        async fn request(self: &Arc<Self>, request: axum::http::request::Builder) -> Response {
            self.send(request, Body::empty()).await
        }

        async fn send(
            self: &Arc<Self>,
            request: axum::http::request::Builder,
            body: impl Into<Body>,
        ) -> Response {
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
                .oneshot(request.body(body.into()).unwrap())
                .await
                .unwrap()
        }

        async fn put(self: &Arc<Self>, path: &str, contents: &'static str) -> StatusCode {
            let uri = format!("/api/files/files/{path}");
            self.send(HttpRequest::put(uri), contents).await.status()
        }

        async fn patch(self: &Arc<Self>, path: &str, to: &str) -> StatusCode {
            let uri = format!("/api/files/files/{path}");
            let body = json!({ "to": to }).to_string();
            self.send(HttpRequest::patch(uri), body).await.status()
        }

        async fn delete(self: &Arc<Self>, path: &str) -> StatusCode {
            let uri = format!("/api/files/files/{path}");
            self.request(HttpRequest::delete(uri)).await.status()
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

    /// The name of a part file for `name`.
    fn part(name: &str) -> String {
        format!(".{name}.{}.part", Uuid::new_v4())
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
            fs::write(host.path(&format!("{index:05}")), "").unwrap();
        }

        let listing = host.json("/api/files/files").await;
        assert_eq!(listing["truncated"], true);
        assert_eq!(listing["entries"].as_array().unwrap().len(), LISTING_CAP);
        assert_eq!(host.names("/api/files/files?after=09999").await, ["10000"]);
    }

    #[tokio::test]
    async fn a_listing_sweeps_only_stale_parts() {
        let (stale, fresh) = (part("a"), part("b"));
        let host = Arc::new(root(&[(&stale, ""), (&fresh, ""), (".c.d.part", "")], &[]));
        let hour_ago = SystemTime::now() - PART_LIFETIME - Duration::from_secs(60);
        for name in [&stale, ".c.d.part"] {
            File::options()
                .write(true)
                .open(host.path(name))
                .unwrap()
                .set_modified(hour_ago)
                .unwrap();
        }

        assert_eq!(
            host.names("/api/files/files?hidden=true").await,
            [fresh, ".c.d.part".to_string()]
        );
        assert!(!host.path(&stale).exists());
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

        let head = host
            .request(HttpRequest::head("/api/files/files/a/b%20c.txt"))
            .await;
        assert_eq!(head.headers()[header::CONTENT_LENGTH], "4");
        assert!(body(head).await.is_empty());

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
        assert_eq!(cached.headers()[header::CONTENT_SECURITY_POLICY], "sandbox");
        assert_eq!(cached.headers()[header::X_CONTENT_TYPE_OPTIONS], "nosniff");
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
        host.link(&host.path("data/raw/y"), "link");

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
        host.link(&host.path("a"), "in");

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

    #[cfg(unix)]
    #[test]
    fn a_file_replaced_after_the_walk_is_not_opened() {
        let host = root(&[("a", "abc"), ("b", "abcd")], &[]);
        let walked = fs::metadata(host.path("a")).unwrap();
        fs::rename(host.path("b"), host.path("a")).unwrap();
        assert!(VerifiedFile::open(host.path("a"), &walked).is_none());

        fs::remove_file(host.path("a")).unwrap();
        std::os::unix::fs::symlink(host.path("x"), host.path("a")).unwrap();
        fs::write(host.path("x"), "abc").unwrap();
        let walked = fs::metadata(host.path("x")).unwrap();
        assert!(VerifiedFile::open(host.path("a"), &walked).is_none());
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

    #[tokio::test]
    async fn an_upload_creates_then_replaces_a_file_and_leaves_no_part() {
        let host = Arc::new(root(&[("a/b", "")], &[]));
        assert_eq!(host.put("a/c.txt", "abcd").await, StatusCode::CREATED);
        assert_eq!(host.contents("a/c.txt").as_deref(), Some("abcd"));
        assert_eq!(host.put("a/c.txt", "abc").await, StatusCode::NO_CONTENT);
        assert_eq!(host.contents("a/c.txt").as_deref(), Some("abc"));
        assert_eq!(
            host.names("/api/files/files/a?hidden=true").await,
            ["b", "c.txt"]
        );
        assert_eq!(host.put("missing/c.txt", "").await, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn an_upload_honors_its_preconditions() {
        let host = Arc::new(root(&[("a", "abc")], &[]));
        let create_only = |path: &str| {
            HttpRequest::put(format!("/api/files/files/{path}")).header(header::IF_NONE_MATCH, "*")
        };
        let if_match =
            |tag: &str| HttpRequest::put("/api/files/files/a").header(header::IF_MATCH, tag);

        assert_eq!(
            host.send(create_only("a"), "x").await.status(),
            StatusCode::PRECONDITION_FAILED
        );
        assert_eq!(
            host.send(create_only("b"), "x").await.status(),
            StatusCode::CREATED
        );
        assert_eq!(
            host.send(if_match("\"0.00000000-0\""), "x").await.status(),
            StatusCode::PRECONDITION_FAILED
        );
        assert_eq!(host.contents("a").as_deref(), Some("abc"));

        let served = host.get("/api/files/files/a").await.headers()[header::ETAG].clone();
        let tag = served.to_str().unwrap();
        assert_eq!(
            host.send(if_match(tag), "abcd").await.status(),
            StatusCode::NO_CONTENT
        );
        let missing = HttpRequest::put("/api/files/files/c").header(header::IF_MATCH, "*");
        assert_eq!(
            host.send(missing, "x").await.status(),
            StatusCode::PRECONDITION_FAILED
        );
        assert_eq!(host.names("/api/files/files?hidden=true").await, ["a", "b"]);
    }

    #[tokio::test]
    async fn an_upload_past_the_limit_is_refused_and_leaves_nothing() {
        let mut host = root(&[], &[]);
        host.max_upload = Some(3);
        let host = Arc::new(host);

        let declared = HttpRequest::put("/api/files/files/a").header(header::CONTENT_LENGTH, "4");
        assert_eq!(
            host.send(declared, "abcd").await.status(),
            StatusCode::PAYLOAD_TOO_LARGE
        );
        assert_eq!(host.put("a", "abcd").await, StatusCode::PAYLOAD_TOO_LARGE);
        assert_eq!(host.put("b", "abc").await, StatusCode::CREATED);
        assert_eq!(host.names("/api/files/files?hidden=true").await, ["b"]);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn an_upload_never_replaces_a_directory_or_a_symlink_or_takes_a_part_name() {
        let host = Arc::new(root(&[("a/b", ""), ("c", "abc")], &[]));
        host.link(&host.path("c"), "d");
        assert_eq!(host.put("a", "x").await, StatusCode::CONFLICT);
        assert_eq!(host.put("d", "x").await, StatusCode::CONFLICT);
        assert_eq!(host.put(&part("e"), "x").await, StatusCode::BAD_REQUEST);
        assert_eq!(host.contents("c").as_deref(), Some("abc"));
    }

    #[tokio::test]
    async fn a_directory_is_created_once() {
        let host = Arc::new(root(&[], &[]));
        let create = || HttpRequest::put("/api/files/files/a?directory");
        assert_eq!(host.request(create()).await.status(), StatusCode::CREATED);
        assert!(host.path("a").is_dir());
        assert_eq!(host.request(create()).await.status(), StatusCode::CONFLICT);
    }

    #[tokio::test]
    async fn a_rename_moves_an_entry_within_the_root() {
        let host = Arc::new(root(&[("a", "abc"), ("b/c", "abcd"), ("d/e", "")], &[]));
        assert_eq!(host.patch("a", "b/f").await, StatusCode::NO_CONTENT);
        assert_eq!(host.contents("b/f").as_deref(), Some("abc"));

        assert_eq!(host.patch("b/f", "b/c").await, StatusCode::CONFLICT);
        assert_eq!(
            host.patch("b/f?overwrite", "b/c").await,
            StatusCode::NO_CONTENT
        );
        assert_eq!(host.contents("b/c").as_deref(), Some("abc"));

        assert_eq!(host.patch("b/c?overwrite", "d").await, StatusCode::CONFLICT);
        assert_eq!(host.patch("d", "d/e/f").await, StatusCode::NOT_FOUND);
        assert_eq!(host.patch("b", "b/g").await, StatusCode::BAD_REQUEST);
        assert_eq!(host.patch("b", "../g").await, StatusCode::BAD_REQUEST);
        assert_eq!(host.patch("b", &part("g")).await, StatusCode::BAD_REQUEST);
        assert_eq!(host.patch("missing", "g").await, StatusCode::NOT_FOUND);
        assert_eq!(host.patch("b", "missing/g").await, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn a_delete_removes_a_full_directory_only_when_asked() {
        let host = Arc::new(root(&[("a", ""), ("b/c", ""), ("d/.e", "")], &[]));
        assert_eq!(host.delete("a").await, StatusCode::NO_CONTENT);
        assert!(!host.path("a").exists());
        assert_eq!(host.delete("b").await, StatusCode::CONFLICT);
        assert_eq!(host.delete("b?recursive").await, StatusCode::NO_CONTENT);
        assert!(!host.path("b").exists());
        assert_eq!(host.delete("missing").await, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn the_root_itself_is_never_written() {
        let host = Arc::new(root(&[("a", "")], &[]));
        let root = |method: Method| {
            HttpRequest::builder()
                .method(method)
                .uri("/api/files/files")
        };
        for method in [Method::PUT, Method::PATCH, Method::DELETE] {
            let status = host
                .send(root(method.clone()), "{\"to\": \"b\"}")
                .await
                .status();
            assert_eq!(status, StatusCode::BAD_REQUEST, "{method}");
        }

        assert_eq!(host.patch("a", "").await, StatusCode::BAD_REQUEST);
        assert!(host.path("a").exists());
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn a_symlink_is_deleted_and_renamed_itself() {
        let outside = TempDir::new().unwrap();
        fs::write(outside.path().join("a"), "abc").unwrap();
        let host = Arc::new(root(&[], &[]));
        host.link(&outside.path().join("a"), "b");
        host.link(&outside.path().join("a"), "c");

        assert_eq!(host.patch("b", "d").await, StatusCode::NO_CONTENT);
        assert!(host.path("d").is_symlink());
        assert_eq!(host.delete("c").await, StatusCode::NO_CONTENT);
        assert_eq!(host.delete("d").await, StatusCode::NO_CONTENT);
        assert!(outside.path().join("a").exists());
    }

    #[tokio::test]
    async fn a_write_refuses_a_read_only_root_and_an_excluded_entry() {
        let mut host = root(&[("a", "abc")], &[]);
        host.writable = false;
        let host = Arc::new(host);
        assert_eq!(host.put("b", "x").await, StatusCode::FORBIDDEN);
        assert_eq!(host.delete("a").await, StatusCode::FORBIDDEN);

        let host = Arc::new(root(&[("data/raw/a", ""), ("data/b", "")], &["/data/raw"]));
        assert_eq!(host.put("data/raw/c", "x").await, StatusCode::NOT_FOUND);
        assert_eq!(host.put("data/raw", "x").await, StatusCode::NOT_FOUND);
        assert_eq!(host.delete("data/raw").await, StatusCode::NOT_FOUND);
        assert_eq!(
            host.patch("data/b", "data/raw").await,
            StatusCode::NOT_FOUND
        );
        assert_eq!(host.patch("data/raw/a", "c").await, StatusCode::NOT_FOUND);

        // Moving or deleting `data` would reach `data/raw`, which no write may.
        assert_eq!(host.delete("data?recursive").await, StatusCode::CONFLICT);
        assert_eq!(host.patch("data", "e").await, StatusCode::CONFLICT);
        assert!(host.path("data/raw/a").exists());
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
    fn only_the_exact_part_shape_is_a_part() {
        assert!(is_part(&part("a.txt")));
        for name in [
            ".a.part",
            ".a.b.part",
            "a.0.part",
            &format!("..{}.part", Uuid::new_v4()),
        ] {
            assert!(!is_part(name), "{name}");
        }
    }

    #[test]
    fn an_attachment_falls_back_to_ascii() {
        assert_eq!(
            attachment("a \"b\" é.txt"),
            "attachment; filename=\"a _b_ _.txt\"; filename*=UTF-8''a%20%22b%22%20%C3%A9%2Etxt"
        );
    }
}
