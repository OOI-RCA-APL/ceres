//! Remuxing a live source into one fragmented MP4 stream that survives reconnects.

mod timeline;

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, SyncSender};
use std::sync::{Arc, Mutex, PoisonError};
use std::thread;
use std::time::{Duration, Instant};

use self::timeline::Timeline;
use crate::error::INPUT_CHANGED;
use crate::{
    Interrupt, MediaError, MediaInput, MediaOutput, MediaPacket, MediaTrack, MediaTranscoder,
    TimeBase,
};

/// The most bytes one chunk of the stream carries.
const CHUNK_SIZE: usize = 65536;

/// The time base re-encoded video is timed in, RTP's video clock.
const TRANSCODE_TIME_BASE: TimeBase = TimeBase { num: 1, den: 90000 };

/// How many chunks wait for the consumer before the session stops reading its source.
///
/// A chunk is about one fragment, so eight absorb a few hundred milliseconds of consumer
/// hiccup before the camera connection backs up, and hold at most 512 KiB per client.
const CHUNK_BACKLOG: usize = 8;

/// Where a remux session gets its connections.
pub trait RemuxSource: Send + 'static {
    /// Opens the next connection, calling `interrupt` from blocking calls, or `None` when the
    /// source has nothing more to give.
    fn connect(&mut self, interrupt: Interrupt) -> Option<Result<MediaInput, MediaError>>;
}

/// An RTSP camera, reached over `transport`, `tcp` or `udp`.
pub struct RtspSource {
    pub url: String,
    pub transport: String,
}

impl RemuxSource for RtspSource {
    fn connect(&mut self, interrupt: Interrupt) -> Option<Result<MediaInput, MediaError>> {
        let options = [("rtsp_transport", self.transport.as_str())];
        Some(MediaInput::open_with(&self.url, &options, Some(interrupt)))
    }
}

/// The delay between reconnect attempts.
#[derive(Debug, Clone, Copy)]
pub struct RemuxBackoff {
    pub initial: Duration,
    pub cap: Duration,
    /// A session lasting this long resets the delay to `initial`.
    pub healthy: Duration,
}

impl Default for RemuxBackoff {
    fn default() -> Self {
        Self {
            initial: Duration::from_millis(500),
            cap: Duration::from_secs(10),
            healthy: Duration::from_secs(5),
        }
    }
}

impl RemuxBackoff {
    /// The delay after a session that lasted `session`, given the delay used before it.
    fn next(&self, delay: Duration, session: Duration) -> Duration {
        if session >= self.healthy {
            self.initial
        } else {
            delay
        }
    }

    /// The delay to use after waiting `delay` once.
    fn grow(&self, delay: Duration) -> Duration {
        (delay * 2).min(self.cap)
    }
}

/// How a remux session writes its stream and treats a lost source.
#[derive(Debug, Clone, Copy)]
pub struct RemuxOptions {
    /// Whether the source's packets are copied as they are, rather than re-encoded as H.264.
    pub copy: bool,
    /// The longest a fragment may run before the muxer flushes it.
    pub fragment_duration: Duration,
    /// Whether fragments carry the DASH `sidx` index.
    pub dash: bool,
    /// Whether a lost source is reconnected, rather than ending the stream.
    pub reconnect: bool,
    /// How long the source may go without delivering a packet before it counts as lost.
    pub stall_timeout: Option<Duration>,
    pub backoff: RemuxBackoff,
}

impl Default for RemuxOptions {
    fn default() -> Self {
        Self {
            copy: true,
            fragment_duration: Duration::from_millis(50),
            dash: true,
            reconnect: true,
            stall_timeout: Some(Duration::from_secs(10)),
            backoff: RemuxBackoff::default(),
        }
    }
}

type Chunk = Result<Vec<u8>, MediaError>;

/// A fragmented MP4 stream remuxed from a source on its own thread, read in chunks.
///
/// Stopping or dropping the stream ends the session, interrupting any blocking FFmpeg call.
pub struct RemuxStream {
    chunks: Mutex<Receiver<Chunk>>,
    stop: Arc<AtomicBool>,
    // Never sent on, dropping it wakes a session waiting out a backoff delay.
    wake: Mutex<Option<SyncSender<()>>>,
}

impl RemuxStream {
    /// Starts remuxing `source` on a new thread.
    pub fn start(source: impl RemuxSource, options: RemuxOptions) -> Self {
        let (chunk_sender, chunks) = mpsc::sync_channel(CHUNK_BACKLOG);
        let (wake, wake_receiver) = mpsc::sync_channel(0);
        let stop = Arc::new(AtomicBool::new(false));
        let session = Session {
            options,
            chunks: chunk_sender,
            wake: wake_receiver,
            stop: Arc::clone(&stop),
            started: Instant::now(),
            touched: Arc::new(AtomicU64::new(0)),
        };
        thread::Builder::new()
            .name("ceres-remux".into())
            .spawn(move || session.run(source))
            .expect("the remux thread spawns");
        Self {
            chunks: Mutex::new(chunks),
            stop,
            wake: Mutex::new(Some(wake)),
        }
    }

    /// Blocks for the next chunk, `None` once the stream ends.
    pub fn next(&self) -> Option<Chunk> {
        let chunks = self.chunks.lock().unwrap_or_else(PoisonError::into_inner);
        chunks.recv().ok()
    }

    /// Ends the session, which closes the stream once any buffered chunks are read.
    pub fn stop(&self) {
        self.stop.store(true, Ordering::Relaxed);
        self.wake
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .take();
    }
}

impl Drop for RemuxStream {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Why one connection's relay ended.
enum RelayEnd {
    /// The connection closed, with the error that closed it, and a reconnect may continue
    /// the stream.
    Disconnected(Option<MediaError>),
    /// The source's codec parameters changed, so the stream cannot continue the same track.
    Changed,
    /// The consumer is gone or the muxer failed, so the stream is over.
    Fatal(Option<MediaError>),
}

struct Muxer {
    output: MediaOutput,
    time_base: TimeBase,
    timeline: Timeline,
}

impl Muxer {
    /// Writes `packet`, timed in `time_base`, onto the stream's timeline.
    fn write(&mut self, packet: &mut MediaPacket, time_base: TimeBase) -> Result<(), MediaError> {
        let timing = packet.timing().rescale(time_base, self.time_base);
        packet.set_timing(self.timeline.place(timing));
        self.output.write(0, packet, self.time_base)
    }
}

/// A session's re-encoding state, which outlives each connection so the encoder's output stays
/// one track.
struct Transcode {
    transcoder: MediaTranscoder,
    /// Places each connection's packets on the decoder's timeline.
    timeline: Timeline,
}

struct Session {
    options: RemuxOptions,
    chunks: SyncSender<Chunk>,
    wake: Receiver<()>,
    stop: Arc<AtomicBool>,
    started: Instant,
    // Milliseconds since `started` at the last sign of life from the source.
    touched: Arc<AtomicU64>,
}

impl Session {
    fn run(self, mut source: impl RemuxSource) {
        let mut muxer = None;
        let mut transcode = None;
        let mut delay = self.options.backoff.initial;
        loop {
            let connected = Instant::now();
            self.touch();
            let end = match source.connect(self.interrupt()) {
                // A source with nothing more to give ends the stream cleanly.
                None => break,
                Some(Err(error)) => RelayEnd::Disconnected(Some(error)),
                Some(Ok(mut input)) if self.options.copy => self.copy(&mut input, &mut muxer),
                Some(Ok(mut input)) => self.transcode(&mut input, &mut muxer, &mut transcode),
            };
            if self.stopped() {
                return;
            }
            let reason = match end {
                RelayEnd::Disconnected(error) if self.options.reconnect => error,
                RelayEnd::Disconnected(Some(error)) if muxer.is_none() => {
                    self.send(Err(error));
                    return;
                }
                RelayEnd::Disconnected(_) | RelayEnd::Changed => break,
                RelayEnd::Fatal(error) => {
                    if let Some(error) = error {
                        self.send(Err(error));
                    }
                    return;
                }
            };
            delay = self.options.backoff.next(delay, connected.elapsed());
            match reason {
                Some(error) => {
                    log::debug!("the source was lost, reconnecting in {delay:?}: {error}");
                }
                None => log::debug!("the source ended, reconnecting in {delay:?}"),
            }
            if !self.sleep(delay) {
                return;
            }
            delay = self.options.backoff.grow(delay);
        }
        if let Some(muxer) = muxer
            && !self.stopped()
            && let Err(error) = muxer.output.finish()
        {
            self.send(Err(error));
        }
    }

    /// Copies `input`'s video into the muxer until the connection ends.
    fn copy(&self, input: &mut MediaInput, muxer: &mut Option<Muxer>) -> RelayEnd {
        let video = match input.video_stream() {
            Ok(video) => video,
            Err(error) => return RelayEnd::Disconnected(Some(error)),
        };
        let track = input.track(video);
        let muxer = match muxer {
            Some(muxer) => match muxer.output.matches(0, &track) {
                Ok(true) => {
                    muxer.timeline.reconnect();
                    muxer
                }
                Ok(false) => return RelayEnd::Changed,
                Err(error) => return RelayEnd::Fatal(Some(error)),
            },
            None => match self.open(&track) {
                Ok(opened) => muxer.insert(opened),
                Err(error) => return self.fatal(error),
            },
        };
        let time_base = track.time_base();
        let mut packet = MediaPacket::new();
        loop {
            if let Err(end) = self.read(input, video, &mut packet) {
                return end;
            }
            if let Err(error) = muxer.write(&mut packet, time_base) {
                return self.fatal(error);
            }
        }
    }

    /// Decodes `input`'s video and re-encodes it into the muxer until the connection ends.
    ///
    /// The encoder lasts the session, so the muxer's track continues across connections for as
    /// long as the source's picture keeps its size and format.
    fn transcode(
        &self,
        input: &mut MediaInput,
        muxer: &mut Option<Muxer>,
        transcode: &mut Option<Transcode>,
    ) -> RelayEnd {
        let video = match input.video_stream() {
            Ok(video) => video,
            Err(error) => return RelayEnd::Disconnected(Some(error)),
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
                }),
                Err(error) => return self.fatal(error),
            },
        };
        // A source whose codec has no decoder fails the same way on every connection.
        if let Err(error) = transcode.transcoder.connect(input, video) {
            return self.fatal(error);
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
                return self.fatal(error);
            }
            loop {
                match transcode.transcoder.receive(&mut packet) {
                    Ok(true) => {}
                    Ok(false) => break,
                    Err(error) if error.code == INPUT_CHANGED => return RelayEnd::Changed,
                    Err(error) => return self.fatal(error),
                }
                let muxer = match muxer {
                    Some(muxer) => muxer,
                    None => {
                        let track = transcode.transcoder.track().expect("an encoded packet");
                        match self.open(&track) {
                            Ok(opened) => muxer.insert(opened),
                            Err(error) => return self.fatal(error),
                        }
                    }
                };
                if let Err(error) = muxer.write(&mut packet, TRANSCODE_TIME_BASE) {
                    return self.fatal(error);
                }
            }
        }
    }

    /// Reads `input`'s next packet of stream `video`, or how the connection ended.
    fn read(
        &self,
        input: &mut MediaInput,
        video: usize,
        packet: &mut MediaPacket,
    ) -> Result<(), RelayEnd> {
        loop {
            self.touch();
            match input.read(packet) {
                Ok(true) if packet.stream() == video => return Ok(()),
                Ok(true) => {}
                Ok(false) => return Err(RelayEnd::Disconnected(None)),
                Err(error) => return Err(RelayEnd::Disconnected(Some(error))),
            }
        }
    }

    fn open(&self, track: &MediaTrack<'_>) -> Result<Muxer, MediaError> {
        let movflags = if self.options.dash {
            "+empty_moov+default_base_moof+dash"
        } else {
            "+empty_moov+default_base_moof"
        };
        let fragment = self.options.fragment_duration.as_micros().to_string();
        let options = [
            ("movflags", movflags),
            ("frag_duration", fragment.as_str()),
            ("flush_packets", "1"),
        ];
        let chunks = self.chunks.clone();
        let sink = Box::new(move |bytes: &[u8]| {
            chunks
                .send(Ok(bytes.to_vec()))
                .map_err(|_| std::io::Error::from(std::io::ErrorKind::BrokenPipe))
        });
        let output = MediaOutput::open("mp4", &options, &[*track], CHUNK_SIZE, sink)?;
        let time_base = output.time_base(0)?;
        Ok(Muxer {
            output,
            time_base,
            timeline: Timeline::default(),
        })
    }

    /// Ends the stream on a muxer failure, quietly when the consumer caused it by leaving.
    fn fatal(&self, error: MediaError) -> RelayEnd {
        RelayEnd::Fatal((!self.stopped()).then_some(error))
    }

    fn interrupt(&self) -> Interrupt {
        let stop = Arc::clone(&self.stop);
        let touched = Arc::clone(&self.touched);
        let started = self.started;
        let timeout = self.options.stall_timeout;
        Box::new(move || {
            stop.load(Ordering::Relaxed)
                || timeout.is_some_and(|timeout| {
                    let last = Duration::from_millis(touched.load(Ordering::Relaxed));
                    started.elapsed().saturating_sub(last) > timeout
                })
        })
    }

    fn touch(&self) {
        let now = u64::try_from(self.started.elapsed().as_millis()).unwrap_or(u64::MAX);
        self.touched.store(now, Ordering::Relaxed);
    }

    fn stopped(&self) -> bool {
        self.stop.load(Ordering::Relaxed)
    }

    fn send(&self, chunk: Chunk) {
        // A consumer that left has no use for the chunk.
        let _ = self.chunks.send(chunk);
    }

    /// Waits `delay`, false when the consumer left meanwhile.
    fn sleep(&self, delay: Duration) -> bool {
        match self.wake.recv_timeout(delay) {
            Err(RecvTimeoutError::Timeout) => !self.stopped(),
            Ok(()) | Err(RecvTimeoutError::Disconnected) => false,
        }
    }
}

#[cfg(test)]
mod tests;
