//! Remuxing a live source into fragmented MP4 streams that survive reconnects.
//!
//! A reader thread holds the source's connection, reconnecting it as needed, and fans its packets
//! out to every stream reading it. Each stream runs its own muxer on a thread of its own, so one
//! camera connection serves any number of viewers, each joining at the latest keyframe.

mod reader;
mod subscriber;
mod timeline;

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::sync::{Arc, LazyLock, Mutex, MutexGuard, PoisonError};
use std::thread;
use std::time::Duration;

use self::reader::Reader;
use crate::{Interrupt, MediaError, MediaInput, TimeBase};

/// The most bytes one chunk of the stream carries.
const CHUNK_SIZE: usize = 65536;

/// The time base re-encoded video is timed in, RTP's video clock.
const TRANSCODE_TIME_BASE: TimeBase = TimeBase { num: 1, den: 90000 };

/// How many chunks wait for the consumer before a stream stops muxing.
///
/// A chunk is about one fragment, so eight absorb a few hundred milliseconds of consumer
/// hiccup, and hold at most 512 KiB per client.
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
///
/// A shared source's reader takes `copy`, `stall_timeout`, `backoff`, and `linger` from the
/// stream that started it, the rest are each stream's own.
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
    /// How long a shared source stays connected after its last stream leaves, so a viewer
    /// coming straight back finds it open rather than racing its teardown.
    pub linger: Duration,
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
            linger: Duration::from_secs(3),
        }
    }
}

/// What a remuxed stream reports besides its bytes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StreamNotice {
    /// The source was lost, once per outage, with the error that lost it if there was one.
    Lost { reason: Option<String> },
    /// The first attempt to reach the lost source again is due after `delay`.
    Retrying { delay: Duration },
    /// The source's picture is back after an outage that took `attempts` connections and
    /// lasted `outage`.
    Reconnected { attempts: u32, outage: Duration },
    /// The stream ended on its own, rather than its consumer stopping it.
    Ended { reason: String },
}

/// One read from a remuxed stream.
#[derive(Debug)]
pub enum StreamItem {
    Chunk(Vec<u8>),
    Notice(StreamNotice),
}

type Chunk = Result<StreamItem, MediaError>;

/// The readers of shared sources by key, each removing itself as it closes.
static READERS: LazyLock<Mutex<HashMap<String, Arc<Reader>>>> = LazyLock::new(Mutex::default);

fn readers() -> MutexGuard<'static, HashMap<String, Arc<Reader>>> {
    READERS.lock().unwrap_or_else(PoisonError::into_inner)
}

/// A fragmented MP4 stream remuxed from a source, read in chunks.
///
/// Stopping or dropping the stream ends it, and its source closes once no stream reads it.
pub struct RemuxStream {
    chunks: Mutex<Receiver<Chunk>>,
    reader: Arc<Reader>,
    id: u64,
    stopped: Arc<AtomicBool>,
}

impl RemuxStream {
    /// Starts remuxing `source` for this stream alone.
    pub fn start(source: impl RemuxSource, options: RemuxOptions) -> Self {
        let reader = Reader::new(None, options);
        let stream = Self::join(&reader, options);
        reader.spawn(source);
        stream
    }

    /// Joins the stream to the source known as `key`, starting it from `source` when no stream
    /// reads it yet.
    pub fn shared<S: RemuxSource>(
        key: String,
        source: impl FnOnce() -> S,
        options: RemuxOptions,
    ) -> Self {
        let mut readers = readers();
        if let Some(reader) = readers.get(&key) {
            return Self::join(reader, options);
        }
        let reader = Reader::new(Some(key.clone()), options);
        readers.insert(key, Arc::clone(&reader));
        let stream = Self::join(&reader, options);
        reader.spawn(source());
        stream
    }

    fn join(reader: &Arc<Reader>, options: RemuxOptions) -> Self {
        let (chunk_sender, chunks) = mpsc::sync_channel(CHUNK_BACKLOG);
        let stopped = Arc::new(AtomicBool::new(false));
        let feeding = reader.join();
        let id = feeding.id;
        let muxing = subscriber::Subscriber::new(options, chunk_sender, Arc::clone(&stopped));
        thread::Builder::new()
            .name("ceres-remux".into())
            .spawn(move || muxing.run(feeding))
            .expect("the remux thread spawns");
        Self {
            chunks: Mutex::new(chunks),
            reader: Arc::clone(reader),
            id,
            stopped,
        }
    }

    /// Blocks for the next chunk or notice, `None` once the stream ends.
    pub fn next(&self) -> Option<Chunk> {
        let chunks = self.chunks.lock().unwrap_or_else(PoisonError::into_inner);
        chunks.recv().ok()
    }

    /// Ends the stream, which closes once any buffered chunks are read.
    pub fn stop(&self) {
        if !self.stopped.swap(true, Ordering::Relaxed) {
            self.reader.leave(self.id);
        }
    }
}

impl Drop for RemuxStream {
    fn drop(&mut self) {
        self.stop();
    }
}

#[cfg(test)]
mod tests;
