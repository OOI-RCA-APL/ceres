//! Responses whose body the host described rather than serialized.
//!
//! A procedure declaring a media type answers with a file to stream or a chunk stream to
//! pull, plus the headers the host already decided. Either body carries a release guard
//! holding the handle, so the host hears about the end whether the body finished, failed,
//! or the client left, which is what runs the output's exit hook.

use std::path::PathBuf;
use std::sync::Arc;

use axum::body::{Body, Bytes};
use axum::http::{HeaderName, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use tokio::io::AsyncReadExt;

use crate::error::ApiError;
use crate::host::{Host, HostError, Served};

/// How much of a file crosses at a time, the size the framework's file responses read.
const CHUNK: usize = 64 * 1024;

/// Holds a host stream open for as long as the body it belongs to lives.
///
/// Releasing has to happen even when the body is dropped rather than drained, so it runs
/// from `Drop` on the runtime captured at construction, which is the runtime serving the
/// request.
struct Release {
    host: Arc<dyn Host>,
    handle: u64,
    runtime: tokio::runtime::Handle,
}

impl Drop for Release {
    fn drop(&mut self) {
        let host = self.host.clone();
        let handle = self.handle;
        self.runtime
            .spawn(async move { host.stream_close(handle).await });
    }
}

/// Serve a described response, streaming its body from a file or from the host.
pub(crate) async fn respond(host: &Arc<dyn Host>, served: Served) -> Response {
    let release = Release {
        host: host.clone(),
        handle: served.handle,
        runtime: tokio::runtime::Handle::current(),
    };

    let body = match served.file {
        Some(path) => match file_body(&path, release).await {
            Ok(body) => body,
            // The host stats the file before describing it, so a failure here is the file
            // going away underneath a response that has not started yet.
            Err(_) => {
                return ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, "error").into_response();
            }
        },
        None => chunk_body(host.clone(), served.handle, release),
    };

    let mut response = Response::new(body);
    *response.status_mut() = StatusCode::from_u16(served.status).unwrap_or(StatusCode::OK);
    for (name, value) in &served.headers {
        if let (Ok(name), Ok(value)) = (
            HeaderName::try_from(name.as_str()),
            HeaderValue::try_from(value.as_str()),
        ) {
            response.headers_mut().append(name, value);
        }
    }

    response
}

/// Stream a file from disk, the release riding along until the last chunk.
async fn file_body(path: &PathBuf, release: Release) -> std::io::Result<Body> {
    let file = tokio::fs::File::open(path).await?;
    let stream =
        futures_util::stream::try_unfold((file, release), |(mut file, release)| async move {
            let mut buffer = vec![0u8; CHUNK];
            let read = file.read(&mut buffer).await?;
            if read == 0 {
                return Ok::<_, std::io::Error>(None);
            }

            buffer.truncate(read);
            Ok(Some((Bytes::from(buffer), (file, release))))
        });
    Ok(Body::from_stream(stream))
}

/// Pull a body's chunks from the host until it reports the end.
fn chunk_body(host: Arc<dyn Host>, handle: u64, release: Release) -> Body {
    let stream =
        futures_util::stream::try_unfold((host, release), move |(host, release)| async move {
            match host.next_chunk(handle).await? {
                Some(chunk) => Ok::<_, HostError>(Some((Bytes::from(chunk), (host, release)))),
                None => Ok(None),
            }
        });
    Body::from_stream(stream)
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use http_body_util::BodyExt;

    use super::*;
    use crate::host::{HostError, UserRecord};

    /// A host handing out a fixed set of chunks and recording what was released.
    #[derive(Default)]
    struct ChunkHost {
        chunks: Mutex<Vec<Vec<u8>>>,
        released: Arc<Mutex<Vec<u64>>>,
    }

    #[async_trait::async_trait]
    impl Host for ChunkHost {
        async fn user(&self, _id: uuid::Uuid) -> Result<Option<UserRecord>, HostError> {
            Ok(None)
        }

        async fn verify_login(
            &self,
            _username: String,
            _password: String,
        ) -> Result<Option<UserRecord>, HostError> {
            Ok(None)
        }

        async fn change_password(
            &self,
            _user: uuid::Uuid,
            _old_password: String,
            _new_password: String,
        ) -> Result<Option<UserRecord>, HostError> {
            Ok(None)
        }

        async fn next_chunk(&self, _handle: u64) -> Result<Option<Vec<u8>>, HostError> {
            let mut chunks = self.chunks.lock().unwrap();
            if chunks.is_empty() {
                return Ok(None);
            }

            Ok(Some(chunks.remove(0)))
        }

        async fn stream_close(&self, handle: u64) {
            self.released.lock().unwrap().push(handle);
        }
    }

    /// Give the release its spawned close a chance to run.
    async fn settle() {
        for _ in 0..8 {
            tokio::task::yield_now().await;
        }
    }

    fn chunk_host(chunks: &[&str]) -> (Arc<dyn Host>, Arc<Mutex<Vec<u64>>>) {
        let released = Arc::new(Mutex::new(Vec::new()));
        let host = ChunkHost {
            chunks: Mutex::new(
                chunks
                    .iter()
                    .map(|chunk| chunk.as_bytes().to_vec())
                    .collect(),
            ),
            released: released.clone(),
        };
        (Arc::new(host), released)
    }

    fn description(handle: u64, file: Option<PathBuf>) -> Served {
        Served {
            status: 206,
            headers: vec![("content-type".to_string(), "text/csv".to_string())],
            file,
            handle,
        }
    }

    #[tokio::test]
    async fn a_chunk_body_streams_and_releases_its_handle() {
        let (host, released) = chunk_host(&["one,", "two"]);

        let response = respond(&host, description(7, None)).await;
        assert_eq!(response.status(), 206);
        assert_eq!(response.headers()["content-type"], "text/csv");

        let body = response.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(&body[..], b"one,two");
        settle().await;
        assert_eq!(*released.lock().unwrap(), vec![7]);
    }

    #[tokio::test]
    async fn a_body_dropped_before_it_ends_still_releases_its_handle() {
        // What a client leaving mid-download looks like from here, and the exit hook the
        // release runs has to fire for it too.
        let (host, released) = chunk_host(&["one,", "two"]);

        let response = respond(&host, description(9, None)).await;
        drop(response);

        settle().await;
        assert_eq!(*released.lock().unwrap(), vec![9]);
    }

    #[tokio::test]
    async fn a_file_body_streams_from_disk_and_releases_its_handle() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("export.csv");
        std::fs::write(&path, "a,b\n1,2\n").unwrap();
        let (host, released) = chunk_host(&[]);

        let response = respond(&host, description(3, Some(path))).await;
        let body = response.into_body().collect().await.unwrap().to_bytes();

        assert_eq!(&body[..], b"a,b\n1,2\n");
        settle().await;
        assert_eq!(*released.lock().unwrap(), vec![3]);
    }

    #[tokio::test]
    async fn a_file_that_cannot_be_opened_refuses_and_releases_its_handle() {
        let (host, released) = chunk_host(&[]);
        let missing = PathBuf::from("/nonexistent/export.csv");

        let response = respond(&host, description(4, Some(missing))).await;

        assert_eq!(response.status(), 500);
        settle().await;
        assert_eq!(*released.lock().unwrap(), vec![4]);
    }
}
