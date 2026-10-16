//! Sessions served to a str0m peer standing in for a browser, over loopback.

use std::net::{Ipv4Addr, SocketAddr, UdpSocket};
use std::sync::Arc;
use std::time::{Duration, Instant};

use ceres_config::{ServerWebrtcConfig, TimeDelta};
use ceres_media::{RtspServer, RtspServerOptions};
use ceres_webrtc::{LiveSource, ReorderedFrames, WebrtcError, WebrtcServer};
use str0m::change::{SdpAnswer, SdpPendingOffer};
use str0m::media::{Direction, Frequency, MediaKind};
use str0m::net::{Protocol, Receive};
use str0m::{Candidate, Event, Input, Output, Rtc, RtcConfig};

#[tokio::test(flavor = "multi_thread")]
async fn a_browser_receives_the_sources_keyframe() {
    let rtsp = source_server("h264");
    let server = server(4);
    let (browser, offer) = Browser::offer();
    let answer = server
        .open(source(&rtsp), &offer, ReorderedFrames::Refuse)
        .await
        .unwrap();
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
    let rtsp = RtspServer::start(
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
        ..source(&rtsp)
    };
    let answer = server
        .open(source, &offer, ReorderedFrames::Refuse)
        .await
        .unwrap();
    let _browser = browser.accept(&answer.sdp);
    ended(answer.closed).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_session_ends_once_its_source_starts_reordering_frames() {
    // The source reconnects to a server that has since been set to send B-frames.
    let rtsp = RtspServer::start(
        "127.0.0.1:0".parse().unwrap(),
        RtspServerOptions {
            clips: vec!["h264".into(), "h264-bframes".into()],
            drop_after: Some(Duration::from_secs(1)),
            ..RtspServerOptions::default()
        },
    )
    .unwrap();
    let server = server(4);
    let (browser, offer) = Browser::offer();
    let answer = server
        .open(source(&rtsp), &offer, ReorderedFrames::Refuse)
        .await
        .unwrap();
    let _browser = browser.accept(&answer.sdp);
    ended(answer.closed).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_browser_connecting_late_starts_from_the_picture_held_for_it() {
    // The source falls silent before the browser connects, so only the held picture can play.
    let rtsp = RtspServer::start(
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
        ..source(&rtsp)
    };
    let answer = server
        .open(source, &offer, ReorderedFrames::Refuse)
        .await
        .unwrap();
    tokio::time::sleep(Duration::from_secs(3)).await;
    let browser = browser.accept(&answer.sdp);

    let picture = tokio::task::spawn_blocking(move || browser.first_picture());
    assert_eq!(picture.await.unwrap(), Some(true));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_browser_that_never_connects_gives_up_its_slot() {
    let rtsp = source_server("h264");
    let no_ice_timeout = TimeDelta::from_secs(1);
    let config = ServerWebrtcConfig {
        no_ice_timeout,
        ..config(1)
    };
    let server = bound(&config);
    let (_silent, offer) = Browser::offer();
    let answer = server
        .open(source(&rtsp), &offer, ReorderedFrames::Refuse)
        .await
        .unwrap();
    tokio::time::sleep(no_ice_timeout.duration() + Duration::from_millis(500)).await;
    assert!(!server.close(&answer.id).await);
    let (_next, offer) = Browser::offer();
    server
        .open(source(&rtsp), &offer, ReorderedFrames::Refuse)
        .await
        .unwrap();
}

#[tokio::test(flavor = "multi_thread")]
async fn a_session_past_the_limit_is_refused() {
    let rtsp = source_server("h264");
    let server = server(1);
    let (_first, offer) = Browser::offer();
    server
        .open(source(&rtsp), &offer, ReorderedFrames::Refuse)
        .await
        .unwrap();
    let (_second, offer) = Browser::offer();
    let refused = server
        .open(source(&rtsp), &offer, ReorderedFrames::Refuse)
        .await;
    assert!(matches!(refused, Err(WebrtcError::Full)), "{refused:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn an_h265_source_reaches_a_browser_that_decodes_it() {
    let rtsp = source_server("h265-no-bframes");
    let server = server(4);
    let (browser, offer) = Browser::offer_with_h265();
    let answer = server
        .open(source(&rtsp), &offer, ReorderedFrames::Refuse)
        .await
        .unwrap();
    let browser = browser.accept(&answer.sdp);

    let picture = tokio::task::spawn_blocking(move || browser.first_picture());
    assert_eq!(
        picture.await.unwrap(),
        Some(true),
        "the first picture is not a keyframe"
    );
    assert!(server.close(&answer.id).await);
}

#[tokio::test(flavor = "multi_thread")]
async fn an_h265_source_to_a_browser_without_it_or_a_bad_offer_is_refused() {
    let server = server(4);
    let (_browser, offer) = Browser::offer();
    let refused = server
        .open(
            source(&source_server("h265")),
            &offer,
            ReorderedFrames::Refuse,
        )
        .await;
    assert!(matches!(refused, Err(WebrtcError::Codec(_))), "{refused:?}");
    let refused = server
        .open(
            source(&source_server("h264")),
            "abc",
            ReorderedFrames::Refuse,
        )
        .await;
    assert!(matches!(refused, Err(WebrtcError::Offer(_))), "{refused:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn a_source_reordering_frames_is_refused() {
    let server = server(4);
    let (_browser, offer) = Browser::offer();
    let refused = server
        .open(
            source(&source_server("h264-bframes")),
            &offer,
            ReorderedFrames::Refuse,
        )
        .await;
    assert!(
        matches!(refused, Err(WebrtcError::Reordered)),
        "{refused:?}"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn dropping_unreferenced_frames_sends_the_rest_in_display_order() {
    let rtsp = source_server("h264-bframes");
    let server = server(4);
    let (browser, offer) = Browser::offer();
    let answer = server
        .open(source(&rtsp), &offer, ReorderedFrames::Drop)
        .await
        .unwrap();
    let browser = browser.accept(&answer.sdp);

    // Two seconds of a 25 fps clip whose every other frame is an unreferenced B-frame.
    let pictures = tokio::task::spawn_blocking(move || browser.pictures(25))
        .await
        .unwrap();
    assert_eq!(pictures.len(), 25, "too few pictures arrived");
    assert!(pictures[0].1, "the first picture is not a keyframe");
    let times: Vec<u64> = pictures.iter().map(|(time, _)| *time).collect();
    assert!(
        times.windows(2).all(|pair| pair[0] < pair[1]),
        "pictures arrived out of display order: {times:?}"
    );
    // Every other frame dropped, so each picture is two frames of 3600 ticks after the last.
    // A keyframe follows the 25-frame group's last P-frame directly, and the source sends its
    // first frame with no time of its own, so the step to the second picture is placed.
    assert!(
        pictures
            .windows(2)
            .skip(1)
            .all(|pair| pair[1].1 || pair[1].0 - pair[0].0 == 7200),
        "a picture was not dropped, or a reference was: {times:?}"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_source_whose_referenced_frames_reorder_is_refused_even_dropping() {
    // The H.265 clip's B-frames reference one another, so dropping the rest leaves reordering.
    let server = server(4);
    let (_browser, offer) = Browser::offer_with_h265();
    let refused = server
        .open(
            source(&source_server("h265")),
            &offer,
            ReorderedFrames::Drop,
        )
        .await;
    assert!(
        matches!(refused, Err(WebrtcError::Reordered)),
        "{refused:?}"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn an_unreachable_source_is_refused() {
    let server = server(4);
    let (_browser, offer) = Browser::offer();
    let source = LiveSource {
        reconnect: false,
        ..source(&source_server("h264"))
    };
    let source = LiveSource {
        url: "rtsp://127.0.0.1:1/stream".into(),
        ..source
    };
    let refused = server.open(source, &offer, ReorderedFrames::Refuse).await;
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

fn source_server(clip: &str) -> RtspServer {
    let options = RtspServerOptions {
        clips: vec![clip.into()],
        ..RtspServerOptions::default()
    };
    RtspServer::start("127.0.0.1:0".parse().unwrap(), options).unwrap()
}

fn server(max_sessions: u64) -> WebrtcServer {
    bound(&config(max_sessions))
}

fn bound(config: &ServerWebrtcConfig) -> WebrtcServer {
    WebrtcServer::bind(Ipv4Addr::LOCALHOST.into(), config).unwrap()
}

fn config(max_sessions: u64) -> ServerWebrtcConfig {
    ServerWebrtcConfig {
        port: 0,
        max_sessions,
        ..ServerWebrtcConfig::default()
    }
}

fn source(rtsp: &RtspServer) -> LiveSource {
    LiveSource {
        url: rtsp.url(),
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
    /// Returns the peer and its offer to receive one H.264 video track, as a browser that
    /// cannot decode H.265 makes.
    fn offer() -> (Self, String) {
        Self::offering(false)
    }

    /// As [`Browser::offer`], offering H.265 as well.
    fn offer_with_h265() -> (Self, String) {
        Self::offering(true)
    }

    fn offering(h265: bool) -> (Self, String) {
        let socket = UdpSocket::bind("127.0.0.1:0").unwrap();
        let mut rtc = RtcConfig::new()
            .set_crypto_provider(Arc::new(str0m::crypto::from_feature_flags()))
            .clear_codecs()
            .enable_h264(true)
            .enable_h265(h265)
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
    fn first_picture(self) -> Option<bool> {
        self.pictures(1).first().map(|(_, key)| *key)
    }

    /// Runs the peer until `count` pictures arrive or ten seconds pass, returning each one's
    /// RTP time in 90 kHz ticks and whether it is a keyframe.
    fn pictures(mut self, count: usize) -> Vec<(u64, bool)> {
        let mut pictures = Vec::new();
        let deadline = Instant::now() + Duration::from_secs(10);
        let local = self.socket.local_addr().unwrap();
        let mut buffer = vec![0; 2048];
        while Instant::now() < deadline && pictures.len() < count {
            let timeout = match self.rtc.poll_output().unwrap() {
                Output::Event(Event::MediaData(data)) => {
                    pictures.push((
                        data.time.rebase(Frequency::NINETY_KHZ).numer(),
                        data.is_keyframe(),
                    ));
                    continue;
                }
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
        pictures
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
