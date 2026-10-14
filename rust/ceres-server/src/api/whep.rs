//! The WHEP routes, which play a procedure's live camera to a browser over WebRTC.
//!
//! The browser posts its SDP offer beside the procedure's call route, with the same query
//! arguments, and the host answers with the camera the procedure's output reads instead of
//! the output's bytes. The answer SDP comes back with the session's own URL, which a
//! `DELETE` ends.

use std::sync::Arc;

use axum::Router;
use axum::body::Bytes;
use axum::extract::{Path, RawQuery, State};
use axum::http::{HeaderMap, StatusCode, Uri, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, post};
use ceres_webrtc::{WebrtcError, WebrtcServer};
use uuid::Uuid;

use crate::api::dispatch::Dispatch;
use crate::app::AppState;
use crate::error::ApiError;
use crate::host::Answer;

/// The route a browser posts its offer to.
pub(crate) const OPEN: &str = "/api/components/{id}/procedures/{second}/whep";

/// The route of one session, which the open route's `Location` header names.
pub(crate) const CLOSE: &str = "/api/components/{id}/procedures/{second}/whep/{session}";

const SDP: &str = "application/sdp";

/// Register both routes.
pub(crate) fn register(router: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    router.route(OPEN, post(open)).route(CLOSE, delete(close))
}

async fn open(
    Path((address, name)): Path<(String, String)>,
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    uri: Uri,
    RawQuery(query): RawQuery,
    body: Bytes,
) -> Result<Response, ApiError> {
    let webrtc = server(&state)?;
    if headers
        .get(header::CONTENT_TYPE)
        .is_none_or(|kind| kind != SDP)
    {
        return Err(ApiError::http(StatusCode::UNSUPPORTED_MEDIA_TYPE));
    }
    let offer = std::str::from_utf8(&body).map_err(|_| ApiError::http(StatusCode::BAD_REQUEST))?;

    let call = Dispatch::procedure("procedures.live", address, name);
    // The host holds the procedure's output open under the handle until told it is done.
    let (source, handle) = match call.answer(&state, &headers, query).await? {
        Answer::Live { source, handle } => (source, handle),
        Answer::Payload(_) => return Err(refusal(StatusCode::CONFLICT, "not-live")),
        Answer::Served(served) => {
            state.host.stream_close(served.handle).await;
            return Err(refusal(StatusCode::CONFLICT, "not-live"));
        }
    };
    let answer = match webrtc.open(source, offer).await {
        Ok(answer) => answer,
        Err(error) => {
            state.host.stream_close(handle).await;
            return Err(refused(error));
        }
    };
    let host = Arc::clone(&state.host);
    let closed = answer.closed;
    tokio::spawn(async move {
        // A dropped sender resolves the wait too, so the handle closes however the session ends.
        let _ = closed.await;
        host.stream_close(handle).await;
    });
    let location = format!("{}/{}", uri.path(), answer.id);
    Ok((
        StatusCode::CREATED,
        [
            (header::CONTENT_TYPE, SDP.to_string()),
            (header::LOCATION, location),
        ],
        answer.sdp,
    )
        .into_response())
}

/// Ends a session, admitting whoever holds its URL.
///
/// The session's ID is a v4 UUID, 122 random bits that only the browser it was answered to
/// knows, so it is the capability, and the most it grants is ending that one session.
async fn close(
    Path((_, _, session)): Path<(String, String, String)>,
    State(state): State<Arc<AppState>>,
) -> Result<StatusCode, ApiError> {
    let webrtc = server(&state)?;
    if session.parse::<Uuid>().is_err() || !webrtc.close(&session).await {
        return Err(ApiError::not_found());
    }
    Ok(StatusCode::OK)
}

/// The server's WebRTC sessions, refused as unavailable when WebRTC is off.
fn server(state: &AppState) -> Result<&Arc<WebrtcServer>, ApiError> {
    let unavailable = || refusal(StatusCode::SERVICE_UNAVAILABLE, "disabled");
    state.webrtc.as_ref().ok_or_else(unavailable)
}

/// The refusal a session that could not open answers with, its `reason` the console's cue
/// to play the procedure's output instead.
///
/// The error's own text stays out of the body, since a source's can carry the camera's URL
/// and its credentials.
fn refused(error: WebrtcError) -> ApiError {
    match error {
        WebrtcError::Full => refusal(StatusCode::SERVICE_UNAVAILABLE, "full"),
        WebrtcError::Offer(_) => refusal(StatusCode::BAD_REQUEST, "offer"),
        WebrtcError::Codec(_) => refusal(StatusCode::CONFLICT, "codec"),
        WebrtcError::Source(_) => refusal(StatusCode::BAD_GATEWAY, "source"),
        WebrtcError::Timeout => refusal(StatusCode::GATEWAY_TIMEOUT, "timeout"),
    }
}

fn refusal(status: StatusCode, reason: &str) -> ApiError {
    let mut error = ApiError::http(status);
    error.fields.insert("reason".to_string(), reason.into());
    error
}

#[cfg(test)]
mod tests {
    use std::net::Ipv4Addr;
    use std::sync::Mutex;
    use std::time::{Duration, Instant};

    use axum::body::Body;
    use axum::http::Request;
    use ceres_config::ServerWebrtcConfig;
    use ceres_media::{RtspServer, RtspServerOptions};
    use ceres_webrtc::LiveSource;
    use http_body_util::BodyExt;
    use serde_json::{Value, json};
    use str0m::RtcConfig;
    use str0m::media::{Direction, MediaKind};
    use tower::ServiceExt;

    use super::*;
    use crate::app::{AppConfig, build_router};
    use crate::host::{Host, HostError, Served, UserRecord};

    const PROCEDURE: &str = "/api/components/abc/procedures/video/whep";

    /// A host whose procedures play `live`, recording the arguments of every call and the
    /// handles it is told to close.
    #[derive(Default)]
    struct LiveHost {
        live: Option<LiveSource>,
        /// Whether a procedure that is not live answers with a body, as a media output does.
        served: bool,
        calls: Mutex<Vec<Value>>,
        closed: Mutex<Vec<u64>>,
        closing: tokio::sync::Notify,
    }

    impl LiveHost {
        /// The handles the host was told to close, once it was told to close any.
        async fn closed(&self) -> Vec<u64> {
            let told = async {
                loop {
                    let closing = self.closing.notified();
                    if !self.closed.lock().unwrap().is_empty() {
                        break;
                    }
                    closing.await;
                }
            };
            tokio::time::timeout(Duration::from_secs(10), told)
                .await
                .unwrap();
            self.closed.lock().unwrap().clone()
        }
    }

    #[async_trait::async_trait]
    impl Host for LiveHost {
        async fn user(&self, _id: Uuid) -> Result<Option<UserRecord>, HostError> {
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
            _: Uuid,
            _: String,
            _: String,
        ) -> Result<Option<UserRecord>, HostError> {
            Ok(None)
        }

        async fn operate(&self, operation: &str, arguments: Value) -> Result<Answer, HostError> {
            assert_eq!(operation, "procedures.live");
            self.calls.lock().unwrap().push(arguments);
            match &self.live {
                Some(live) => Ok(Answer::Live {
                    source: live.clone(),
                    handle: 7,
                }),
                None if self.served => Ok(Answer::Served(Served {
                    status: 200,
                    headers: Vec::new(),
                    file: None,
                    handle: 7,
                })),
                // What the operation answers for a procedure whose output reads no camera.
                None => Ok(Answer::Payload("null".into())),
            }
        }

        async fn stream_close(&self, handle: u64) {
            self.closed.lock().unwrap().push(handle);
            self.closing.notify_one();
        }
    }

    /// Returns the app over `host`, serving WebRTC on a free port when `webrtc` is set.
    fn app(host: &Arc<LiveHost>, webrtc: bool) -> Router {
        let config = ServerWebrtcConfig {
            port: 0,
            ..ServerWebrtcConfig::default()
        };
        build_router(AppConfig {
            console: None,
            cli_token: None,
            auth: None,
            host: Arc::clone(host) as Arc<dyn Host>,
            version: "0.0.0".to_string(),
            authority: None,
            webrtc: webrtc.then(|| {
                Arc::new(WebrtcServer::bind(Ipv4Addr::LOCALHOST.into(), &config).unwrap())
            }),
        })
    }

    fn host(clip: Option<&RtspServer>) -> Arc<LiveHost> {
        let live = clip.map(|camera| LiveSource {
            url: camera.url(),
            transport: "tcp".into(),
            copy: true,
            // A camera that stops ends the session, so its output closes.
            reconnect: false,
            stall_timeout: Some(Duration::from_secs(5)),
        });
        Arc::new(LiveHost {
            live,
            ..LiveHost::default()
        })
    }

    fn camera(clip: &str) -> RtspServer {
        let options = RtspServerOptions {
            clips: vec![clip.into()],
            ..RtspServerOptions::default()
        };
        RtspServer::start("127.0.0.1:0".parse().unwrap(), options).unwrap()
    }

    /// A browser's offer to receive one video track.
    fn offer() -> String {
        let mut rtc = RtcConfig::new()
            .set_crypto_provider(Arc::new(str0m::crypto::from_feature_flags()))
            .build(Instant::now());
        let mut changes = rtc.sdp_api();
        changes.add_media(MediaKind::Video, Direction::RecvOnly, None, None, None);
        changes.apply().unwrap().0.to_sdp_string()
    }

    async fn post(app: &Router, path: &str, kind: &str) -> Response {
        let request = Request::post(path)
            .header(header::CONTENT_TYPE, kind)
            .body(Body::from(offer()))
            .unwrap();
        app.clone().oneshot(request).await.unwrap()
    }

    async fn delete(app: &Router, path: &str) -> StatusCode {
        let request = Request::delete(path).body(Body::empty()).unwrap();
        app.clone().oneshot(request).await.unwrap().status()
    }

    /// Returns a refusal's status and the `reason` its envelope gives.
    async fn refused(response: Response) -> (StatusCode, Value) {
        let status = response.status();
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let envelope: Value = serde_json::from_slice(&body).unwrap();
        (status, envelope["reason"].clone())
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_live_procedure_answers_at_its_session_url_until_deleted() {
        let camera = camera("h264");
        let host = host(Some(&camera));
        let app = app(&host, true);

        let response = post(&app, &format!("{PROCEDURE}?zoom=2"), SDP).await;
        assert_eq!(response.status(), StatusCode::CREATED);
        assert_eq!(response.headers()[header::CONTENT_TYPE], SDP);
        let location = response.headers()[header::LOCATION]
            .to_str()
            .unwrap()
            .to_string();
        let session = location.strip_prefix(&format!("{PROCEDURE}/")).unwrap();
        assert!(session.parse::<Uuid>().is_ok(), "{location}");
        let body = response.into_body().collect().await.unwrap().to_bytes();
        assert!(body.starts_with(b"v=0"));

        let call = host.calls.lock().unwrap()[0].clone();
        assert_eq!(call["path"], json!({"address": "abc", "name": "video"}));
        assert_eq!(call["query"], json!([["zoom", "2"]]));
        assert!(host.closed.lock().unwrap().is_empty());

        assert_eq!(delete(&app, &location).await, StatusCode::OK);
        assert_eq!(host.closed().await, [7]);
        assert_eq!(delete(&app, &location).await, StatusCode::NOT_FOUND);
        assert_eq!(host.closed().await, [7]);
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_session_whose_camera_stops_closes_its_procedure_output() {
        let options = RtspServerOptions {
            clips: vec!["h264".into()],
            drop_after: Some(Duration::from_secs(1)),
            ..RtspServerOptions::default()
        };
        let camera = RtspServer::start("127.0.0.1:0".parse().unwrap(), options).unwrap();
        let host = host(Some(&camera));
        let app = app(&host, true);
        assert_eq!(
            post(&app, PROCEDURE, SDP).await.status(),
            StatusCode::CREATED
        );
        assert_eq!(host.closed().await, [7]);
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn an_offer_that_cannot_play_is_refused_with_its_reason() {
        let off = app(&host(None), false);
        let disabled = (StatusCode::SERVICE_UNAVAILABLE, json!("disabled"));
        assert_eq!(refused(post(&off, PROCEDURE, SDP).await).await, disabled);

        let not_live = app(&host(None), true);
        let conflict = (StatusCode::CONFLICT, json!("not-live"));
        assert_eq!(
            refused(post(&not_live, PROCEDURE, SDP).await).await,
            conflict
        );
        let response = post(&not_live, PROCEDURE, "text/plain").await;
        assert_eq!(response.status(), StatusCode::UNSUPPORTED_MEDIA_TYPE);

        let camera = camera("h265");
        let h265 = host(Some(&camera));
        let codec = (StatusCode::CONFLICT, json!("codec"));
        let response = post(&app(&h265, true), PROCEDURE, SDP).await;
        assert_eq!(refused(response).await, codec);
        assert_eq!(*h265.closed.lock().unwrap(), [7]);
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_media_output_that_is_not_live_is_closed_and_refused() {
        let host = Arc::new(LiveHost {
            served: true,
            ..LiveHost::default()
        });
        let app = app(&host, true);
        let conflict = (StatusCode::CONFLICT, json!("not-live"));
        assert_eq!(refused(post(&app, PROCEDURE, SDP).await).await, conflict);
        assert_eq!(*host.closed.lock().unwrap(), [7]);
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn deleting_an_unknown_session_is_not_found() {
        let app = app(&host(None), true);
        let unknown = format!("{PROCEDURE}/{}", Uuid::new_v4());
        assert_eq!(delete(&app, &unknown).await, StatusCode::NOT_FOUND);
        assert_eq!(
            delete(&app, &format!("{PROCEDURE}/abc")).await,
            StatusCode::NOT_FOUND
        );
    }
}
