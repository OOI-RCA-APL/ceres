use std::collections::VecDeque;
use std::io::Write;
use std::sync::mpsc::{self, Sender};
use std::thread;
use std::time::Instant;

use super::*;
use crate::{MediaPacket, RtspServer, RtspServerOptions, fixture};

enum Attempt {
    Clip(&'static str),
    Fail,
}

use Attempt::{Clip, Fail};

/// A source whose connections open fixture clips, or fail, in order.
struct Attempts(VecDeque<Attempt>);

impl RemuxSource for Attempts {
    fn connect(&mut self, _interrupt: Interrupt) -> Option<Result<MediaInput, MediaError>> {
        Some(match self.0.pop_front()? {
            Clip(codec) => MediaInput::open(&fixture(&format!("{codec}.mp4"))),
            Fail => Err(MediaError::invalid("abc")),
        })
    }
}

/// A source whose connection blocks until interrupted, then reports it.
struct Hanging(Sender<()>);

impl RemuxSource for Hanging {
    fn connect(&mut self, interrupt: Interrupt) -> Option<Result<MediaInput, MediaError>> {
        while !interrupt() {
            thread::sleep(Duration::from_millis(5));
        }
        let _ = self.0.send(());
        None
    }
}

fn options(reconnect: bool) -> RemuxOptions {
    let delay = Duration::from_millis(10);
    RemuxOptions {
        reconnect,
        backoff: RemuxBackoff {
            initial: delay,
            cap: delay,
            healthy: Duration::from_secs(5),
        },
        ..RemuxOptions::default()
    }
}

/// Everything a stream gave until it ended or a deadline passed.
#[derive(Default)]
struct Drained {
    bytes: Vec<u8>,
    notices: Vec<StreamNotice>,
    error: Option<MediaError>,
}

/// Reads the stream until it ends or `deadline` passes.
fn drain_all(stream: &RemuxStream, deadline: Option<Instant>) -> Drained {
    let mut drained = Drained::default();
    while deadline.is_none_or(|deadline| Instant::now() < deadline) {
        match stream.next() {
            Some(Ok(StreamItem::Chunk(chunk))) => drained.bytes.extend(chunk),
            Some(Ok(StreamItem::Notice(notice))) => drained.notices.push(notice),
            Some(Err(error)) => {
                drained.error = Some(error);
                break;
            }
            None => break,
        }
    }
    drained
}

/// Reads the stream until it ends or `deadline` passes, returning its bytes and the error
/// that ended it.
fn drain(stream: &RemuxStream, deadline: Option<Instant>) -> (Vec<u8>, Option<MediaError>) {
    let drained = drain_all(stream, deadline);
    (drained.bytes, drained.error)
}

/// The decode timestamp of every packet in `bytes`, read back through the demuxer.
fn decode_timestamps(bytes: &[u8]) -> Vec<i64> {
    if bytes.is_empty() {
        return Vec::new();
    }
    let mut file = tempfile::Builder::new().suffix(".mp4").tempfile().unwrap();
    file.write_all(bytes).unwrap();
    let mut input = MediaInput::open(file.path().to_str().unwrap()).unwrap();
    let mut packet = MediaPacket::new();
    let mut stamps = Vec::new();
    // A stream cut off mid-fragment ends in a read error, and the packets before it count.
    while let Ok(true) = input.read(&mut packet) {
        stamps.push(packet.timing().dts.unwrap());
    }
    stamps
}

fn remux<const N: usize>(
    attempts: [Attempt; N],
    reconnect: bool,
) -> (Vec<i64>, Option<MediaError>) {
    let stream = RemuxStream::start(Attempts(attempts.into()), options(reconnect));
    let (bytes, error) = drain(&stream, None);
    (decode_timestamps(&bytes), error)
}

fn serve(options: RtspServerOptions) -> RtspServer {
    RtspServer::start("127.0.0.1:0".parse().unwrap(), options).unwrap()
}

fn rtsp(server: &RtspServer) -> RtspSource {
    RtspSource {
        url: server.url(),
        transport: "tcp".to_owned(),
    }
}

#[test]
fn reconnect_continues_one_timeline() {
    let (stamps, error) = remux([Clip("h264"), Clip("h264")], true);
    assert!(error.is_none(), "{error:?}");
    assert_eq!(stamps.len(), 200);
    assert!(stamps.is_sorted_by(|a, b| a < b));
}

#[test]
fn failed_connection_is_retried() {
    let (stamps, error) = remux([Fail, Clip("h265")], true);
    assert!(error.is_none(), "{error:?}");
    assert_eq!(stamps.len(), 100);
}

#[test]
fn codec_change_ends_the_stream() {
    let (stamps, error) = remux([Clip("h264"), Clip("h265"), Clip("h264")], true);
    assert!(error.is_none(), "{error:?}");
    assert_eq!(stamps.len(), 100);
}

#[test]
fn failed_first_connection_without_reconnect_is_an_error() {
    let (stamps, error) = remux([Fail, Clip("h264")], false);
    assert!(stamps.is_empty());
    assert!(error.unwrap().message.contains("abc"));
}

#[test]
fn lost_source_without_reconnect_ends_the_stream() {
    let (stamps, error) = remux([Clip("h264"), Clip("h264")], false);
    assert!(error.is_none(), "{error:?}");
    assert_eq!(stamps.len(), 100);
}

/// The stream's bytes and ending error, re-encoding each attempt's clip in turn.
fn reencode<const N: usize>(attempts: [Attempt; N]) -> (Vec<u8>, Option<MediaError>) {
    let options = RemuxOptions {
        copy: false,
        ..options(true)
    };
    drain(
        &RemuxStream::start(Attempts(attempts.into()), options),
        None,
    )
}

fn contains(bytes: &[u8], tag: &[u8]) -> bool {
    bytes.windows(tag.len()).any(|window| window == tag)
}

#[test]
fn reencoding_writes_h264() {
    let (bytes, error) = reencode([Clip("h265")]);
    assert!(error.is_none(), "{error:?}");
    assert!(contains(&bytes, b"avc1") && !contains(&bytes, b"hvc1"));
    // The decoder holds a few frames of reordering delay that a lost source never flushes.
    let stamps = decode_timestamps(&bytes);
    assert!(stamps.len() > 90, "{} packets", stamps.len());
}

#[test]
fn reencoding_continues_one_timeline_across_a_codec_change() {
    let (bytes, error) = reencode([Clip("h264"), Clip("h265")]);
    assert!(error.is_none(), "{error:?}");
    let stamps = decode_timestamps(&bytes);
    assert!(stamps.len() > 180, "{} packets", stamps.len());
    assert!(stamps.is_sorted_by(|a, b| a < b));
}

#[test]
fn reencoding_ten_bit_video_is_an_error() {
    let (bytes, error) = reencode([Clip("h265-10bit"), Clip("h265-10bit")]);
    assert!(bytes.is_empty());
    let error = error.expect("an error");
    assert!(error.message.contains("8-bit 4:2:0"), "{error}");
}

#[test]
fn backoff_doubles_to_the_cap_and_resets_after_a_healthy_session() {
    let backoff = RemuxBackoff::default();
    let short = Duration::from_secs(1);
    let delays = [0.5, 1.0, 2.0, 4.0, 8.0, 10.0, 10.0].map(Duration::from_secs_f64);
    let mut delay = backoff.initial;
    for expected in delays {
        delay = backoff.next(delay, short);
        assert_eq!(delay, expected);
        delay = backoff.grow(delay);
    }
    assert_eq!(backoff.next(delay, backoff.healthy), backoff.initial);
}

#[test]
fn stalled_source_is_lost() {
    let server = serve(RtspServerOptions {
        stall_after: Some(Duration::from_secs(1)),
        ..RtspServerOptions::default()
    });
    let options = RemuxOptions {
        stall_timeout: Some(Duration::from_secs(1)),
        ..options(false)
    };
    let started = Instant::now();
    let stream = RemuxStream::start(rtsp(&server), options);
    let (bytes, error) = drain(&stream, None);
    assert!(error.is_none(), "{error:?}");
    assert!(started.elapsed() < Duration::from_secs(6));
    assert!(!decode_timestamps(&bytes).is_empty());
}

#[test]
fn dropped_rtsp_session_is_reconnected() {
    let server = serve(RtspServerOptions {
        drop_after: Some(Duration::from_secs(1)),
        ..RtspServerOptions::default()
    });
    let stream = RemuxStream::start(rtsp(&server), options(true));
    let (bytes, error) = drain(&stream, Some(Instant::now() + Duration::from_secs(5)));
    assert!(error.is_none(), "{error:?}");
    let stamps = decode_timestamps(&bytes);
    // One session delivers about a second, 25 frames, so more than 50 took a reconnect.
    assert!(stamps.len() > 50, "{} packets", stamps.len());
    assert!(stamps.is_sorted_by(|a, b| a < b));
}

#[test]
fn reencoded_rtsp_session_is_reconnected() {
    let server = serve(RtspServerOptions {
        drop_after: Some(Duration::from_secs(1)),
        ..RtspServerOptions::default()
    });
    let options = RemuxOptions {
        copy: false,
        ..options(true)
    };
    let stream = RemuxStream::start(rtsp(&server), options);
    let (bytes, error) = drain(&stream, Some(Instant::now() + Duration::from_secs(5)));
    assert!(error.is_none(), "{error:?}");
    let stamps = decode_timestamps(&bytes);
    assert!(stamps.len() > 50, "{} packets", stamps.len());
    assert!(stamps.is_sorted_by(|a, b| a < b));
}

#[test]
fn dropping_the_stream_interrupts_the_source() {
    let (interrupted, receiver) = mpsc::channel();
    let options = RemuxOptions {
        stall_timeout: None,
        ..options(true)
    };
    let stream = RemuxStream::start(Hanging(interrupted), options);
    // Dropped once the reader is inside the blocking connect.
    thread::sleep(Duration::from_millis(50));
    drop(stream);
    receiver.recv_timeout(Duration::from_secs(5)).unwrap();
}

#[test]
fn stopping_the_stream_ends_a_pending_read() {
    let (interrupted, _receiver) = mpsc::channel();
    let options = RemuxOptions {
        stall_timeout: None,
        ..options(true)
    };
    let stream = Arc::new(RemuxStream::start(Hanging(interrupted), options));
    let (done, ended) = mpsc::channel();
    let reader = Arc::clone(&stream);
    thread::spawn(move || done.send(reader.next().is_none()).unwrap());
    thread::sleep(Duration::from_millis(50));
    stream.stop();
    assert!(ended.recv_timeout(Duration::from_secs(5)).unwrap());
}

/// A stream of `server`'s camera joined to the source every other stream of it shares.
fn shared(server: &RtspServer, options: RemuxOptions) -> RemuxStream {
    RemuxStream::shared(server.url(), || rtsp(server), options)
}

/// Whether the first packet of `bytes` is a keyframe.
fn starts_with_keyframe(bytes: &[u8]) -> bool {
    let mut file = tempfile::Builder::new().suffix(".mp4").tempfile().unwrap();
    file.write_all(bytes).unwrap();
    let mut input = MediaInput::open(file.path().to_str().unwrap()).unwrap();
    let mut packet = MediaPacket::new();
    input.read(&mut packet).unwrap() && packet.is_key()
}

/// Reads `stream` on a thread of its own for `duration`.
fn drain_for(stream: RemuxStream, duration: Duration) -> thread::JoinHandle<Drained> {
    thread::spawn(move || drain_all(&stream, Some(Instant::now() + duration)))
}

#[test]
fn streams_of_one_camera_share_its_session() {
    let server = serve(RtspServerOptions {
        max_sessions: Some(1),
        ..RtspServerOptions::default()
    });
    let first = drain_for(shared(&server, options(true)), Duration::from_secs(3));
    thread::sleep(Duration::from_millis(700));
    let second = drain_for(shared(&server, options(true)), Duration::from_secs(2));
    for drained in [first.join().unwrap(), second.join().unwrap()] {
        assert!(drained.error.is_none(), "{:?}", drained.error);
        assert!(drained.notices.is_empty(), "{:?}", drained.notices);
        let stamps = decode_timestamps(&drained.bytes);
        assert!(stamps.len() > 25, "{} packets", stamps.len());
        assert!(stamps.is_sorted_by(|a, b| a < b));
        assert!(starts_with_keyframe(&drained.bytes));
    }
    assert_eq!(server.sessions(), 1);
}

#[test]
fn a_camera_stays_connected_briefly_after_its_last_stream() {
    let server = serve(RtspServerOptions::default());
    let options = RemuxOptions {
        linger: Duration::from_millis(500),
        ..options(true)
    };
    let (bytes, _) = drain(
        &shared(&server, options),
        Some(Instant::now() + Duration::from_secs(1)),
    );
    assert!(!bytes.is_empty());
    let (bytes, _) = drain(
        &shared(&server, options),
        Some(Instant::now() + Duration::from_secs(1)),
    );
    assert!(!bytes.is_empty());
    assert_eq!(server.sessions(), 1);
    drop(shared(&server, options));
    thread::sleep(Duration::from_millis(1500));
    let (bytes, _) = drain(
        &shared(&server, options),
        Some(Instant::now() + Duration::from_secs(1)),
    );
    assert!(!bytes.is_empty());
    assert_eq!(server.sessions(), 2);
}

#[test]
fn an_unread_stream_holds_up_no_other() {
    let server = serve(RtspServerOptions::default());
    let idle = shared(&server, options(true));
    let read = drain_for(shared(&server, options(true)), Duration::from_secs(3));
    let drained = read.join().unwrap();
    let stamps = decode_timestamps(&drained.bytes);
    // The clip runs at 25 frames a second.
    assert!(stamps.len() > 50, "{} packets", stamps.len());
    // The stream left unread catches up from a keyframe, its timeline unbroken.
    let drained = drain_all(&idle, Some(Instant::now() + Duration::from_secs(2)));
    let stamps = decode_timestamps(&drained.bytes);
    assert!(stamps.len() > 25, "{} packets", stamps.len());
    assert!(stamps.is_sorted_by(|a, b| a < b));
}

#[test]
fn a_stream_without_reconnect_ends_while_others_reconnect() {
    let server = serve(RtspServerOptions {
        drop_after: Some(Duration::from_secs(1)),
        ..RtspServerOptions::default()
    });
    let once = drain_for(shared(&server, options(false)), Duration::from_secs(5));
    let always = drain_for(shared(&server, options(true)), Duration::from_secs(5));
    let once = once.join().unwrap();
    assert!(once.error.is_none(), "{:?}", once.error);
    assert!(
        matches!(once.notices.as_slice(), [StreamNotice::Ended { .. }]),
        "{:?}",
        once.notices
    );
    let always = always.join().unwrap();
    assert!(always.error.is_none(), "{:?}", always.error);
    let stamps = decode_timestamps(&always.bytes);
    assert!(
        stamps.len() > 50,
        "{} packets, {:?}",
        stamps.len(),
        always.notices
    );
}

#[test]
fn a_lost_camera_is_reported_once_per_outage() {
    let server = serve(RtspServerOptions {
        restart_after: Some(Duration::from_secs(1)),
        restart_downtime: Duration::from_millis(500),
        ..RtspServerOptions::default()
    });
    let drained = drain_all(
        &shared(&server, options(true)),
        Some(Instant::now() + Duration::from_secs(4)),
    );
    assert!(drained.error.is_none(), "{:?}", drained.error);
    let kinds = drained
        .notices
        .iter()
        .map(|notice| match notice {
            StreamNotice::Lost { .. } => "lost",
            StreamNotice::Retrying { .. } => "retrying",
            StreamNotice::Reconnected { .. } => "reconnected",
            StreamNotice::Ended { .. } => "ended",
        })
        .collect::<Vec<_>>();
    assert_eq!(kinds, ["lost", "retrying", "reconnected"]);
    let Some(StreamNotice::Reconnected { attempts, outage }) = drained.notices.last() else {
        unreachable!();
    };
    assert!(*attempts >= 1);
    assert!(*outage >= Duration::from_millis(400), "{outage:?}");
}

#[test]
fn a_changed_picture_ends_the_streams_that_cannot_continue() {
    let stream = RemuxStream::start(Attempts([Clip("h264"), Clip("h265")].into()), options(true));
    let drained = drain_all(&stream, None);
    assert!(drained.error.is_none(), "{:?}", drained.error);
    assert!(
        matches!(drained.notices.last(), Some(StreamNotice::Ended { .. })),
        "{:?}",
        drained.notices
    );
    assert_eq!(decode_timestamps(&drained.bytes).len(), 100);
}
