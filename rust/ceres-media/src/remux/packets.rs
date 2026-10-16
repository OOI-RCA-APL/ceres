//! A source's packets as they arrive, for a consumer that frames them itself.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use super::order::{FrameOrder, FrameOrderCheck, SharedFrameOrder};
use super::reader::{Feed, Feeding, Reader};
use super::timeline::Timeline;
use super::{RemuxOptions, RemuxSource, StreamNotice, attach};
use crate::{MediaCodec, MediaError, MediaPacket, OwnedTrack, TimeBase, is_unreferenced};

/// One read from a `PacketStream`.
pub enum PacketItem {
    /// The track the following packets belong to, sent first, after each reconnect, and before
    /// the keyframe a stream that fell behind resumes at. A track whose codec or parameter sets
    /// differ from the last one's starts a new picture.
    Track(Arc<OwnedTrack>),
    /// One encoded frame timed in `PacketStream::TIME_BASE`.
    Packet(MediaPacket),
    Notice(StreamNotice),
}

/// A source's video packets, from the latest keyframe, on one timeline across reconnects.
///
/// Packets are relayed as the source sends them, or re-encoded as H.264 without `copy`. Streams
/// of one key share the source's connection with every `RemuxStream` of that key. Stopping or
/// dropping the stream ends it, and its source closes once no stream reads it.
pub struct PacketStream {
    reading: Mutex<Reading>,
    reader: Arc<Reader>,
    id: u64,
    reconnect: bool,
    stopped: AtomicBool,
    /// The order of the current track's frames, as far as the packets read so far tell.
    order: SharedFrameOrder,
    /// As `order`, of only the frames others reference.
    referenced_order: SharedFrameOrder,
}

struct Reading {
    feeding: Feeding,
    timeline: Timeline,
    /// The time base of the last track, which the packets after it are timed in.
    time_base: Option<TimeBase>,
    /// A joining stream's snapshot, read out before the feed.
    queued: VecDeque<Result<PacketItem, MediaError>>,
    /// Whether a packet has been read, so a lost source without reconnect ends the stream
    /// rather than failing it.
    started: bool,
    ended: bool,
    /// The codec of the last track, which tells which of its frames others reference.
    codec: MediaCodec,
    /// Told from the source's own presentation times, since placing them on the timeline
    /// holds each one at or after its decode time, which for a source sending no decode times
    /// hides the reordering.
    order: FrameOrderCheck,
    referenced_order: FrameOrderCheck,
}

impl std::fmt::Debug for PacketItem {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Track(track) => write!(formatter, "Track({:?})", track.codec()),
            Self::Packet(packet) => write!(formatter, "Packet({:?})", packet.timing()),
            Self::Notice(notice) => write!(formatter, "Notice({notice:?})"),
        }
    }
}

impl PacketStream {
    /// The clock every packet is timed in, RTP's video clock.
    pub const TIME_BASE: TimeBase = TimeBase { num: 1, den: 90000 };

    /// The most bytes of packets since the last keyframe worth holding for a consumer not yet
    /// ready to play them, the bound a shared source holds for one joining late.
    pub const GOP_BYTES: usize = super::reader::GOP_CACHE_BYTES;

    /// Starts reading `source` for this stream alone.
    pub fn start(source: impl RemuxSource, options: RemuxOptions) -> Self {
        Self::new(attach(None, || source, options), options)
    }

    /// Joins the stream to the source known as `key`, starting it from `source` when no stream
    /// reads it yet.
    pub fn shared<S: RemuxSource>(
        key: String,
        source: impl FnOnce() -> S,
        options: RemuxOptions,
    ) -> Self {
        Self::new(attach(Some(key), source, options), options)
    }

    fn new((reader, feeding): (Arc<Reader>, Feeding), options: RemuxOptions) -> Self {
        Self {
            id: feeding.id,
            reading: Mutex::new(Reading {
                feeding,
                timeline: Timeline::default(),
                time_base: None,
                queued: VecDeque::new(),
                started: false,
                ended: false,
                codec: MediaCodec::Other,
                order: FrameOrderCheck::default(),
                referenced_order: FrameOrderCheck::default(),
            }),
            reader,
            reconnect: options.reconnect,
            stopped: AtomicBool::new(false),
            order: SharedFrameOrder::default(),
            referenced_order: SharedFrameOrder::default(),
        }
    }

    /// The order the current track's frames arrive in, as far as the packets read so far
    /// tell. A track's first read starts over, and its order is known a few packets after
    /// its keyframe.
    pub fn frame_order(&self) -> FrameOrder {
        self.order.get()
    }

    /// As `frame_order`, of only the frames others reference, the ones left once every frame
    /// `is_unreferenced` finds is dropped.
    pub fn referenced_frame_order(&self) -> FrameOrder {
        self.referenced_order.get()
    }

    /// Blocks for the next track, packet, or notice, `None` once the stream ends.
    pub fn next(&self) -> Option<Result<PacketItem, MediaError>> {
        let mut reading = self.reading();
        loop {
            if let Some(item) = reading.queued.pop_front() {
                let item = item.map(|item| reading.place(item));
                self.order.set(reading.order.order());
                self.referenced_order.set(reading.referenced_order.order());
                return Some(item);
            }
            if reading.ended {
                return None;
            }
            // The reader dropping the stream, as it does when the consumer leaves, ends it.
            let Ok(feed) = reading.feeding.feed.recv() else {
                reading.ended = true;
                return None;
            };
            match feed {
                Feed::Track(track) => reading.queued.push_back(Ok(PacketItem::Track(track))),
                Feed::Snapshot(track, packets) => {
                    reading.queued.push_back(Ok(PacketItem::Track(track)));
                    let packets = packets.into_iter().map(PacketItem::Packet).map(Ok);
                    reading.queued.extend(packets);
                }
                Feed::Packet(packet) => {
                    reading.feeding.pending.fetch_sub(1, Ordering::Relaxed);
                    reading.queued.push_back(Ok(PacketItem::Packet(packet)));
                }
                Feed::Lost(error) => {
                    let item = reading.lost(self.reconnect, error);
                    reading.queued.push_back(item);
                }
                Feed::Notice(notice) => reading.queued.push_back(Ok(PacketItem::Notice(notice))),
                Feed::End(error) => {
                    reading.ended = true;
                    if let Some(error) = error {
                        reading.queued.push_back(Err(error));
                    }
                }
            }
        }
    }

    /// Ends the stream, which closes once any packets already sent to it are read.
    pub fn stop(&self) {
        if !self.stopped.swap(true, Ordering::Relaxed) {
            self.reader.leave(self.id);
        }
    }

    fn reading(&self) -> MutexGuard<'_, Reading> {
        self.reading.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Drop for PacketStream {
    fn drop(&mut self) {
        self.stop();
    }
}

impl Reading {
    /// Times a packet on the stream's timeline, and starts a new connection's stretch of it at
    /// each track.
    fn place(&mut self, item: PacketItem) -> PacketItem {
        match item {
            PacketItem::Track(track) => {
                self.timeline.reconnect();
                self.time_base = Some(track.time_base());
                self.codec = track.codec();
                self.order.reset();
                self.referenced_order.reset();
                PacketItem::Track(track)
            }
            PacketItem::Packet(mut packet) => {
                self.started = true;
                if let Some(time_base) = self.time_base {
                    let timing = packet.timing().rescale(time_base, PacketStream::TIME_BASE);
                    let key = packet.is_key();
                    self.order.observe(timing.pts, key);
                    if !is_unreferenced(packet.data(), self.codec) {
                        self.referenced_order.observe(timing.pts, key);
                    }
                    packet.set_timing(self.timeline.place(timing));
                }
                PacketItem::Packet(packet)
            }
            notice => notice,
        }
    }

    /// Passes a lost source on, or ends a stream that does not reconnect, as a remuxed stream
    /// does.
    fn lost(
        &mut self,
        reconnect: bool,
        error: Option<MediaError>,
    ) -> Result<PacketItem, MediaError> {
        if reconnect {
            return Ok(PacketItem::Notice(StreamNotice::Lost {
                reason: error.as_ref().map(ToString::to_string),
            }));
        }
        self.ended = true;
        if !self.started {
            return Err(error.unwrap_or_else(|| MediaError::invalid("the source sent no video")));
        }
        let reason = match error {
            Some(error) => format!("the source was lost: {error}"),
            None => "the source ended".to_owned(),
        };
        Ok(PacketItem::Notice(StreamNotice::Ended { reason }))
    }
}
