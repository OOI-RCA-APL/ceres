//! Sessions served to a str0m peer standing in for a browser, over loopback.

use std::net::{SocketAddr, UdpSocket};
use std::sync::Arc;
use std::time::{Duration, Instant};

use ceres_config::ServerWebrtcConfig;
use ceres_media::{RtspServer, RtspServerOptions};
use ceres_webrtc::{LiveSource, NO_ICE_TIMEOUT, WebrtcError, WebrtcServer};
use str0m::change::{SdpAnswer, SdpPendingOffer};
use str0m::media::{Direction, MediaKind};
use str0m::net::{Protocol, Receive};
use str0m::{Candidate, Event, Input, Output, Rtc, RtcConfig};

#[tokio::test(flavor = "multi_thread")]
async fn a_browser_receives_the_sources_keyframe() {
    let camera = camera("h264");
    let server = server(4);
    let (browser, offer) = Browser::offer();
    let answer = server.open(source(&camera), &offer).await.unwrap();
    let browser = browser.accept(&answer.sdp);

    let picture = tokio::task::spawn_blocking(move || browser.first_picture());
    assert_eq!(
        picture.await.unwrap(),
        Some(true),
        "the first picture is not a keyframe"
    );
    assert!(server.close(&answer.id).await);
    assert!(!server.close(&answer.id).await);
    ended(answer.closed).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_session_ends_with_its_source() {
    let camera = RtspServer::start(
        "127.0.0.1:0".parse().unwrap(),
        RtspServerOptions {
            clips: vec!["h264".into()],
            drop_after: Some(Duration::from_secs(1)),
            ..RtspServerOptions::default()
        },
    )
    .unwrap();
    let server = server(4);
    let (browser, offer) = Browser::offer();
    let source = LiveSource {
        reconnect: false,
        ..source(&camera)
    };
    let answer = server.open(source, &offer).await.unwrap();
    let _browser = browser.accept(&answer.sdp);
    ended(answer.closed).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_browser_connecting_late_starts_from_the_picture_held_for_it() {
    // The camera falls silent before the browser connects, so only the held picture can play.
    let camera = RtspServer::start(
        "127.0.0.1:0".parse().unwrap(),
        RtspServerOptions {
            clips: vec!["h264".into()],
            // Long enough for the source's probe to find its track.
            stall_after: Some(Duration::from_secs(2)),
            ..RtspServerOptions::default()
        },
    )
    .unwrap();
    let server = server(4);
    let (browser, offer) = Browser::offer();
    let source = LiveSource {
        stall_timeout: None,
        ..source(&camera)
    };
    let answer = server.open(source, &offer).await.unwrap();
    tokio::time::sleep(Duration::from_secs(3)).await;
    let browser = browser.accept(&answer.sdp);

    let picture = tokio::task::spawn_blocking(move || browser.first_picture());
    assert_eq!(picture.await.unwrap(), Some(true));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_browser_that_never_connects_gives_up_its_slot() {
    let camera = camera("h264");
    let server = server(1);
    let (_silent, offer) = Browser::offer();
    let answer = server.open(source(&camera), &offer).await.unwrap();
    tokio::time::sleep(NO_ICE_TIMEOUT + Duration::from_secs(1)).await;
    assert!(!server.close(&answer.id).await);
    let (_next, offer) = Browser::offer();
    server.open(source(&camera), &offer).await.unwrap();
}

#[tokio::test(flavor = "multi_thread")]
async fn a_session_past_the_limit_is_refused() {
    let camera = camera("h264");
    let server = server(1);
    let (_first, offer) = Browser::offer();
    server.open(source(&camera), &offer).await.unwrap();
    let (_second, offer) = Browser::offer();
    let refused = server.open(source(&camera), &offer).await;
    assert!(matches!(refused, Err(WebrtcError::Full)), "{refused:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn an_h265_source_or_a_bad_offer_is_refused() {
    let server = server(4);
    let (_browser, offer) = Browser::offer();
    let refused = server.open(source(&camera("h265")), &offer).await;
    assert!(matches!(refused, Err(WebrtcError::Codec(_))), "{refused:?}");
    let refused = server.open(source(&camera("h264")), "abc").await;
    assert!(matches!(refused, Err(WebrtcError::Offer(_))), "{refused:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn an_unreachable_source_is_refused() {
    let server = server(4);
    let (_browser, offer) = Browser::offer();
    let source = LiveSource {
        reconnect: false,
        ..source(&camera("h264"))
    };
    let source = LiveSource {
        url: "rtsp://127.0.0.1:1/stream".into(),
        ..source
    };
    let refused = server.open(source, &offer).await;
    assert!(
        matches!(refused, Err(WebrtcError::Source(_))),
        "{refused:?}"
    );
}

/// Waits for a session's `closed` to resolve, failing after ten seconds.
async fn ended(closed: tokio::sync::oneshot::Receiver<()>) {
    let waited = tokio::time::timeout(Duration::from_secs(10), closed).await;
    assert!(waited.is_ok(), "the session did not end");
}

fn camera(clip: &str) -> RtspServer {
    let options = RtspServerOptions {
        clips: vec![clip.into()],
        ..RtspServerOptions::default()
    };
    RtspServer::start("127.0.0.1:0".parse().unwrap(), options).unwrap()
}

fn server(max_sessions: u64) -> WebrtcServer {
    let config = ServerWebrtcConfig {
        port: 0,
        max_sessions,
        ..ServerWebrtcConfig::default()
    };
    WebrtcServer::bind(&config).unwrap()
}

fn source(camera: &RtspServer) -> LiveSource {
    LiveSource {
        url: camera.url(),
        transport: "tcp".into(),
        copy: true,
        reconnect: true,
        stall_timeout: Some(Duration::from_secs(5)),
    }
}

/// A receiving peer on a loopback socket of its own.
struct Browser {
    rtc: Rtc,
    socket: UdpSocket,
    pending: Option<SdpPendingOffer>,
}

impl Browser {
    /// Returns the peer and its offer to receive one video track.
    fn offer() -> (Self, String) {
        let socket = UdpSocket::bind("127.0.0.1:0").unwrap();
        let mut rtc = RtcConfig::new()
            .set_crypto_provider(Arc::new(str0m::crypto::from_feature_flags()))
            .clear_codecs()
            .enable_h264(true)
            .build(Instant::now());
        let candidate = Candidate::host(socket.local_addr().unwrap(), "udp").unwrap();
        rtc.add_local_candidate(candidate);
        let mut changes = rtc.sdp_api();
        changes.add_media(MediaKind::Video, Direction::RecvOnly, None, None, None);
        let (offer, pending) = changes.apply().unwrap();
        let browser = Self {
            rtc,
            socket,
            pending: Some(pending),
        };
        (browser, offer.to_sdp_string())
    }

    fn accept(mut self, answer: &str) -> Self {
        let answer = SdpAnswer::from_sdp_string(answer).unwrap();
        let pending = self.pending.take().unwrap();
        self.rtc.sdp_api().accept_answer(pending, answer).unwrap();
        self
    }

    /// Runs the peer until media arrives, answering whether it is a keyframe, or `None` when
    /// none arrives within ten seconds.
    fn first_picture(mut self) -> Option<bool> {
        let deadline = Instant::now() + Duration::from_secs(10);
        let local = self.socket.local_addr().unwrap();
        let mut buffer = vec![0; 2048];
        while Instant::now() < deadline {
            let timeout = match self.rtc.poll_output().unwrap() {
                Output::Event(Event::MediaData(data)) => return Some(data.is_keyframe()),
                Output::Event(_) => continue,
                Output::Transmit(transmit) => {
                    self.socket
                        .send_to(&transmit.contents, transmit.destination)
                        .unwrap();
                    continue;
                }
                Output::Timeout(timeout) => timeout,
            };
            let wait = timeout
                .saturating_duration_since(Instant::now())
                .max(Duration::from_millis(1));
            self.socket.set_read_timeout(Some(wait)).unwrap();
            let input = match self.socket.recv_from(&mut buffer) {
                Ok((length, source)) => receive(source, local, &buffer[..length]),
                Err(_) => Some(Input::Timeout(Instant::now())),
            };
            if let Some(input) = input {
                self.rtc.handle_input(input).unwrap();
            }
        }
        None
    }
}

fn receive(source: SocketAddr, destination: SocketAddr, datagram: &[u8]) -> Option<Input<'_>> {
    let contents = datagram.try_into().ok()?;
    let receive = Receive {
        proto: Protocol::Udp,
        source,
        destination,
        contents,
    };
    Some(Input::Receive(Instant::now(), receive))
}
