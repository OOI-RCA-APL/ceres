//! The thread holding a source's connection and fanning its packets out to every stream.

use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::thread;
use std::time::{Duration, Instant};

use super::timeline::Timeline;
use super::{RemuxOptions, RemuxSource, StreamNotice, TRANSCODE_TIME_BASE, readers};
use crate::error::INPUT_CHANGED;
use crate::{Interrupt, MediaError, MediaInput, MediaPacket, MediaTranscoder, OwnedTrack};

/// How many packets may wait for a stream's muxer before the stream skips to the next keyframe.
pub(super) const FEED_BACKLOG: usize = 256;

/// The most bytes of packets kept since the last keyframe for streams joining mid-picture.
const GOP_CACHE_BYTES: usize = 16 << 20;

/// How often a reader waiting out a backoff delay checks whether it should close.
const POLL: Duration = Duration::from_millis(20);

/// What a reader sends each stream.
pub(super) enum Feed {
    /// The track the following packets belong to, sent for each new connection when copying,
    /// for each new encoder when re-encoding, and before the keyframe a skipping stream resumes
    /// at.
    Track(Arc<OwnedTrack>),
    /// A joining stream's track and the packets since the last keyframe, from that keyframe.
    Snapshot(Arc<OwnedTrack>, Vec<MediaPacket>),
    /// A packet timed in the last track's time base.
    Packet(MediaPacket),
    /// The source was lost, with the error that lost it if there was one.
    Lost(Option<MediaError>),
    Notice(StreamNotice),
    /// The source is done, cleanly or with the error that ended it.
    End(Option<MediaError>),
}

/// A stream's end of a reader.
pub(super) struct Feeding {
    pub(super) id: u64,
    pub(super) feed: Receiver<Feed>,
    /// How many packets the stream has yet to take from `feed`.
    pub(super) pending: Arc<AtomicUsize>,
}

struct Subscriber {
    id: u64,
    sender: Sender<Feed>,
    pending: Arc<AtomicUsize>,
    /// Whether the stream waits for a keyframe, having joined mid-picture or fallen behind.
    waiting: bool,
}

impl Subscriber {
    fn send(&self, feed: Feed) -> bool {
        self.sender.send(feed).is_ok()
    }
}

/// The source's lost spell, from losing it to its picture coming back.
struct Outage {
    since: Instant,
    attempts: u32,
    reason: Option<MediaError>,
    scheduled: bool,
}

#[derive(Default)]
struct State {
    subscribers: Vec<Subscriber>,
    next_id: u64,
    track: Option<Arc<OwnedTrack>>,
    /// The current track's packets since its last keyframe, while `gop_valid`.
    gop: Vec<MediaPacket>,
    gop_bytes: usize,
    gop_valid: bool,
    outage: Option<Outage>,
}

/// A source's connection, shared by the streams reading it.
pub(super) struct Reader {
    /// The key a shared reader is registered under, `None` for a stream's own.
    key: Option<String>,
    options: RemuxOptions,
    state: Mutex<State>,
    started: Instant,
    /// Milliseconds since `started` at the last sign of life from the source.
    touched: AtomicU64,
    /// Milliseconds since `started` when the last stream left, `u64::MAX` while any reads.
    empty_since: AtomicU64,
    closed: AtomicBool,
}

/// Why one connection ended.
enum LinkEnd {
    /// The connection is gone, with the error that ended it, and another may follow.
    Lost(Option<MediaError>),
    /// The source cannot go on, whatever the next connection.
    Fatal(MediaError),
}

/// A reader's re-encoding state, which outlives each connection so the encoder's output stays
/// one track.
struct Transcode {
    transcoder: MediaTranscoder,
    /// Places each connection's packets on the decoder's timeline.
    timeline: Timeline,
    /// Whether streams have the encoder's track yet.
    published: bool,
}

impl Reader {
    pub(super) fn new(key: Option<String>, options: RemuxOptions) -> Arc<Self> {
        Arc::new(Self {
            key,
            options,
            state: Mutex::default(),
            started: Instant::now(),
            touched: AtomicU64::new(0),
            empty_since: AtomicU64::new(u64::MAX),
            closed: AtomicBool::new(false),
        })
    }

    /// Starts reading `source` on a thread of its own.
    pub(super) fn spawn(self: &Arc<Self>, source: impl RemuxSource) {
        let reader = Arc::clone(self);
        thread::Builder::new()
            .name("ceres-remux-reader".into())
            .spawn(move || reader.run(source))
            .expect("the remux reader thread spawns");
    }

    /// Adds a stream, which starts from the latest keyframe.
    pub(super) fn join(&self) -> Feeding {
        let (sender, feed) = mpsc::channel();
        let pending = Arc::new(AtomicUsize::new(0));
        let mut state = self.state();
        let id = state.next_id;
        state.next_id += 1;
        let mut subscriber = Subscriber {
            id,
            sender,
            pending: Arc::clone(&pending),
            waiting: false,
        };
        if let Some(track) = state.track.clone() {
            if state.gop_valid {
                let packets = state
                    .gop
                    .iter()
                    .filter_map(|packet| packet.try_clone().ok())
                    .collect();
                subscriber.send(Feed::Snapshot(track, packets));
            } else {
                subscriber.send(Feed::Track(track));
                subscriber.waiting = true;
            }
        }
        if let Some(outage) = &state.outage {
            subscriber.send(Feed::Lost(outage.reason.clone()));
        }
        if self.closed.load(Ordering::Relaxed) {
            subscriber.send(Feed::End(None));
        }
        state.subscribers.push(subscriber);
        self.empty_since.store(u64::MAX, Ordering::Relaxed);
        Feeding { id, feed, pending }
    }

    /// Removes a stream, which ends once it has taken what was sent to it.
    pub(super) fn leave(&self, id: u64) {
        let mut state = self.state();
        state.subscribers.retain(|subscriber| subscriber.id != id);
        if state.subscribers.is_empty() {
            self.empty_since.store(self.now(), Ordering::Relaxed);
        }
    }

    fn run(self: Arc<Self>, mut source: impl RemuxSource) {
        let mut transcode = None;
        let mut delay = self.options.backoff.initial;
        loop {
            if self.should_stop() && self.try_close() {
                return;
            }
            let connected = Instant::now();
            self.touch();
            let end = match source.connect(self.interrupt()) {
                // A source with nothing more to give ends its streams cleanly.
                None => return self.close(None),
                Some(Err(error)) => LinkEnd::Lost(Some(error)),
                Some(Ok(mut input)) if self.options.copy => self.copy(&mut input),
                Some(Ok(mut input)) => self.transcode(&mut input, &mut transcode),
            };
            let error = match end {
                LinkEnd::Fatal(error) => return self.close(Some(error)),
                LinkEnd::Lost(error) => error,
            };
            if self.should_stop() && self.try_close() {
                return;
            }
            self.lost(error);
            // A stream's own reader reconnects only for a stream that asked for it.
            if self.key.is_none() && !self.options.reconnect {
                return self.close(None);
            }
            delay = self.options.backoff.next(delay, connected.elapsed());
            self.schedule(delay);
            self.sleep(delay);
            delay = self.options.backoff.grow(delay);
        }
    }

    /// Relays `input`'s video packets as they are until the connection ends.
    fn copy(&self, input: &mut MediaInput) -> LinkEnd {
        let video = match input.video_stream() {
            Ok(video) => video,
            Err(error) => return LinkEnd::Lost(Some(error)),
        };
        let track = match input.track(video).to_owned() {
            Ok(track) => Arc::new(track),
            Err(error) => return LinkEnd::Fatal(error),
        };
        {
            let mut state = self.state();
            state.track = Some(Arc::clone(&track));
            state.gop.clear();
            state.gop_bytes = 0;
            state.gop_valid = true;
            Self::broadcast(&mut state, || Feed::Track(Arc::clone(&track)));
        }
        let mut packet = MediaPacket::new();
        loop {
            if let Err(end) = self.read(input, video, &mut packet) {
                return end;
            }
            self.publish(&packet);
        }
    }

    /// Decodes `input`'s video and relays it re-encoded until the connection ends.
    ///
    /// The encoder lasts the reader, so its track continues across connections for as long as
    /// the source's picture keeps its size and format. A picture that changes opens a new
    /// encoder, and with it a new track.
    fn transcode(&self, input: &mut MediaInput, transcode: &mut Option<Transcode>) -> LinkEnd {
        let video = match input.video_stream() {
            Ok(video) => video,
            Err(error) => return LinkEnd::Lost(Some(error)),
        };
        let transcode = match transcode {
            Some(transcode) => {
                transcode.timeline.reconnect();
                transcode
            }
            None => match MediaTranscoder::open(TRANSCODE_TIME_BASE) {
                Ok(transcoder) => transcode.insert(Transcode {
                    transcoder,
                    timeline: Timeline::default(),
                    published: false,
                }),
                Err(error) => return LinkEnd::Fatal(error),
            },
        };
        // A source whose codec has no decoder fails the same way on every connection.
        if let Err(error) = transcode.transcoder.connect(input, video) {
            return LinkEnd::Fatal(error);
        }
        let source = input.time_base(video);
        let mut packet = MediaPacket::new();
        loop {
            if let Err(end) = self.read(input, video, &mut packet) {
                return end;
            }
            let timing = packet.timing().rescale(source, TRANSCODE_TIME_BASE);
            packet.set_timing(transcode.timeline.place(timing));
            if let Err(error) = transcode.transcoder.send(&mut packet) {
                return LinkEnd::Fatal(error);
            }
            loop {
                match transcode.transcoder.receive(&mut packet) {
                    Ok(true) => {}
                    Ok(false) => break,
                    Err(error) if error.code == INPUT_CHANGED => {
                        let reopened = MediaTranscoder::open(TRANSCODE_TIME_BASE).and_then(
                            |mut transcoder| {
                                transcoder.connect(input, video)?;
                                Ok(transcoder)
                            },
                        );
                        match reopened {
                            Ok(transcoder) => {
                                transcode.transcoder = transcoder;
                                transcode.published = false;
                            }
                            Err(error) => return LinkEnd::Fatal(error),
                        }
                        break;
                    }
                    Err(error) => return LinkEnd::Fatal(error),
                }
                if !transcode.published {
                    let track = transcode.transcoder.track().expect("an encoded packet");
                    let track = match track.to_owned() {
                        Ok(track) => Arc::new(track),
                        Err(error) => return LinkEnd::Fatal(error),
                    };
                    let mut state = self.state();
                    state.track = Some(Arc::clone(&track));
                    state.gop.clear();
                    state.gop_bytes = 0;
                    state.gop_valid = true;
                    Self::broadcast(&mut state, || Feed::Track(Arc::clone(&track)));
                    transcode.published = true;
                }
                self.publish(&packet);
            }
        }
    }

    /// Reads `input`'s next packet of stream `video`, or how the connection ended.
    fn read(
        &self,
        input: &mut MediaInput,
        video: usize,
        packet: &mut MediaPacket,
    ) -> Result<(), LinkEnd> {
        loop {
            self.touch();
            match input.read(packet) {
                Ok(true) if packet.stream() == video => {
                    self.received();
                    return Ok(());
                }
                Ok(true) => {}
                Ok(false) => return Err(LinkEnd::Lost(None)),
                Err(error) => return Err(LinkEnd::Lost(Some(error))),
            }
        }
    }

    /// Ends an outage once the source's picture arrives again.
    fn received(&self) {
        let mut state = self.state();
        if let Some(outage) = state.outage.take() {
            let notice = StreamNotice::Reconnected {
                attempts: outage.attempts,
                outage: outage.since.elapsed(),
            };
            Self::broadcast(&mut state, || Feed::Notice(notice.clone()));
        }
    }

    /// Sends `packet` to every stream, and keeps it for streams joining later.
    fn publish(&self, packet: &MediaPacket) {
        let mut state = self.state();
        let key = packet.is_key();
        if key {
            state.gop.clear();
            state.gop_bytes = 0;
            state.gop_valid = true;
        }
        if state.gop_valid {
            state.gop_bytes += packet.size();
            if state.gop_bytes > GOP_CACHE_BYTES {
                // Streams joining before the next keyframe wait for it.
                state.gop.clear();
                state.gop_bytes = 0;
                state.gop_valid = false;
            } else if let Ok(kept) = packet.try_clone() {
                state.gop.push(kept);
            }
        }
        let track = state.track.clone();
        state.subscribers.retain_mut(|subscriber| {
            let pending = subscriber.pending.load(Ordering::Relaxed);
            if subscriber.waiting {
                if !key || pending >= FEED_BACKLOG {
                    return true;
                }
                // The track again tells the stream to continue its timeline from here, as after
                // a reconnect, rather than leave a gap.
                if let Some(track) = &track
                    && !subscriber.send(Feed::Track(Arc::clone(track)))
                {
                    return false;
                }
                subscriber.waiting = false;
            } else if pending >= FEED_BACKLOG {
                subscriber.waiting = true;
                return true;
            }
            let Ok(clone) = packet.try_clone() else {
                return true;
            };
            subscriber.pending.fetch_add(1, Ordering::Relaxed);
            subscriber.send(Feed::Packet(clone))
        });
    }

    /// Notes a lost connection, telling streams once per outage.
    fn lost(&self, error: Option<MediaError>) {
        let mut state = self.state();
        if let Some(outage) = &mut state.outage {
            outage.attempts += 1;
            outage.reason = error;
            return;
        }
        state.outage = Some(Outage {
            since: Instant::now(),
            attempts: 1,
            reason: error.clone(),
            scheduled: false,
        });
        Self::broadcast(&mut state, || Feed::Lost(error.clone()));
    }

    /// Tells streams of the first reconnect attempt each outage.
    fn schedule(&self, delay: Duration) {
        let mut state = self.state();
        if let Some(outage) = &mut state.outage
            && !outage.scheduled
        {
            outage.scheduled = true;
            Self::broadcast(&mut state, || {
                Feed::Notice(StreamNotice::Retrying { delay })
            });
        }
    }

    fn broadcast(state: &mut State, mut feed: impl FnMut() -> Feed) {
        state
            .subscribers
            .retain(|subscriber| subscriber.send(feed()));
    }

    /// Closes for good when no stream reads the source, false when one joined meanwhile.
    fn try_close(&self) -> bool {
        // The registry's lock comes first, as when a stream joins, so no stream joins a reader
        // that is closing.
        let mut registry = self.key.as_ref().map(|_| readers());
        let state = self.state();
        if !state.subscribers.is_empty() {
            return false;
        }
        self.closed.store(true, Ordering::Relaxed);
        if let (Some(registry), Some(key)) = (&mut registry, &self.key) {
            registry.remove(key);
        }
        true
    }

    /// Closes for good, ending every stream cleanly or with `error`.
    fn close(&self, error: Option<MediaError>) {
        let mut registry = self.key.as_ref().map(|_| readers());
        let mut state = self.state();
        self.closed.store(true, Ordering::Relaxed);
        if let (Some(registry), Some(key)) = (&mut registry, &self.key) {
            registry.remove(key);
        }
        drop(registry);
        Self::broadcast(&mut state, || Feed::End(error.clone()));
        state.subscribers.clear();
    }

    /// Whether the reader has had no stream for longer than it lingers.
    fn should_stop(&self) -> bool {
        let empty_since = self.empty_since.load(Ordering::Relaxed);
        if empty_since == u64::MAX {
            return false;
        }
        let linger = if self.key.is_some() {
            self.options.linger
        } else {
            Duration::ZERO
        };
        Duration::from_millis(self.now().saturating_sub(empty_since)) >= linger
    }

    fn interrupt(self: &Arc<Self>) -> Interrupt {
        let reader = Arc::clone(self);
        Box::new(move || reader.should_stop() || reader.stalled())
    }

    fn stalled(&self) -> bool {
        self.options.stall_timeout.is_some_and(|timeout| {
            let last = self.touched.load(Ordering::Relaxed);
            Duration::from_millis(self.now().saturating_sub(last)) > timeout
        })
    }

    fn touch(&self) {
        self.touched.store(self.now(), Ordering::Relaxed);
    }

    fn now(&self) -> u64 {
        u64::try_from(self.started.elapsed().as_millis()).unwrap_or(u64::MAX - 1)
    }

    /// Waits `delay`, or less once the reader should close.
    fn sleep(&self, delay: Duration) {
        let until = Instant::now() + delay;
        while !self.should_stop() {
            let left = until.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return;
            }
            thread::sleep(left.min(POLL));
        }
    }

    fn state(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}
