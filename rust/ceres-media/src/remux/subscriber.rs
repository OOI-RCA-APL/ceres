//! One stream's muxer, fed by its source's reader on a thread of its own.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::SyncSender;

use super::reader::{Feed, Feeding};
use super::timeline::Timeline;
use super::{CHUNK_SIZE, Chunk, RemuxOptions, StreamItem, StreamNotice};
use crate::{MediaError, MediaOutput, MediaPacket, MediaTrack, OwnedTrack, TimeBase};

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

pub(super) struct Subscriber {
    options: RemuxOptions,
    chunks: SyncSender<Chunk>,
    /// Set once the consumer stopped the stream.
    stopped: Arc<AtomicBool>,
}

/// How a stream's muxing ended.
enum End {
    /// Finish the MP4, the stream ending cleanly.
    Finish,
    /// Abandon the stream with this error, or quietly when there is none.
    Fail(Option<MediaError>),
}

impl Subscriber {
    pub(super) fn new(
        options: RemuxOptions,
        chunks: SyncSender<Chunk>,
        stopped: Arc<AtomicBool>,
    ) -> Self {
        Self {
            options,
            chunks,
            stopped,
        }
    }

    pub(super) fn run(self, feeding: Feeding) {
        let mut track = None;
        let mut muxer = None;
        let end = loop {
            // The reader dropping the stream, as it does when the consumer leaves, ends it.
            let Ok(feed) = feeding.feed.recv() else {
                break End::Finish;
            };
            let result = match feed {
                Feed::Track(next) => self.track(&mut track, &mut muxer, next),
                Feed::Snapshot(next, packets) => {
                    self.track(&mut track, &mut muxer, next).and_then(|()| {
                        packets
                            .into_iter()
                            .try_for_each(|packet| self.write(track.as_deref(), &mut muxer, packet))
                    })
                }
                Feed::Packet(packet) => {
                    feeding.pending.fetch_sub(1, Ordering::Relaxed);
                    self.write(track.as_deref(), &mut muxer, packet)
                }
                Feed::Lost(error) => self.lost(muxer.is_some(), error),
                Feed::Notice(notice) => {
                    self.notice(notice);
                    Ok(())
                }
                Feed::End(None) => Err(End::Finish),
                Feed::End(Some(error)) => Err(End::Fail(Some(error))),
            };
            if let Err(end) = result {
                break end;
            }
        };
        if self.stopped() {
            return;
        }
        match (end, muxer) {
            (End::Finish, Some(muxer)) => {
                if let Err(error) = muxer.output.finish() {
                    self.send(Err(error));
                }
            }
            (End::Fail(Some(error)), _) => self.send(Err(error)),
            _ => {}
        }
    }

    /// Takes the track the next packets belong to, continuing the stream's timeline when it
    /// matches the one the muxer opened with.
    fn track(
        &self,
        track: &mut Option<Arc<OwnedTrack>>,
        muxer: &mut Option<Muxer>,
        next: Arc<OwnedTrack>,
    ) -> Result<(), End> {
        if let Some(muxer) = muxer {
            match muxer.output.matches(0, &next.track()) {
                Ok(true) => muxer.timeline.reconnect(),
                Ok(false) => {
                    let reason = if self.options.copy {
                        "the source's codec, picture size, or parameter sets changed"
                    } else {
                        "the source's picture size or pixel format changed"
                    };
                    self.notice(StreamNotice::Ended {
                        reason: reason.to_owned(),
                    });
                    return Err(End::Finish);
                }
                Err(error) => return Err(self.fatal(error)),
            }
        }
        *track = Some(next);
        Ok(())
    }

    /// Writes `packet`, opening the muxer on the first one.
    fn write(
        &self,
        track: Option<&OwnedTrack>,
        muxer: &mut Option<Muxer>,
        mut packet: MediaPacket,
    ) -> Result<(), End> {
        let Some(track) = track else {
            return Ok(());
        };
        let muxer = match muxer {
            Some(muxer) => muxer,
            None => match self.open(&track.track()) {
                Ok(opened) => muxer.insert(opened),
                Err(error) => return Err(self.fatal(error)),
            },
        };
        muxer
            .write(&mut packet, track.track().time_base())
            .map_err(|error| self.fatal(error))
    }

    /// Passes a lost source on, or ends a stream that does not reconnect.
    fn lost(&self, started: bool, error: Option<MediaError>) -> Result<(), End> {
        if self.options.reconnect {
            self.notice(StreamNotice::Lost {
                reason: error.as_ref().map(ToString::to_string),
            });
            return Ok(());
        }
        if !started {
            // A stream that never got a picture fails with whatever kept it away.
            let error = error.unwrap_or_else(|| MediaError::invalid("the source sent no video"));
            return Err(End::Fail(Some(error)));
        }
        let reason = match error {
            Some(error) => format!("the source was lost: {error}"),
            None => "the source ended".to_owned(),
        };
        self.notice(StreamNotice::Ended { reason });
        Err(End::Finish)
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
                .send(Ok(StreamItem::Chunk(bytes.to_vec())))
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
    fn fatal(&self, error: MediaError) -> End {
        End::Fail((!self.stopped()).then_some(error))
    }

    fn notice(&self, notice: StreamNotice) {
        self.send(Ok(StreamItem::Notice(notice)));
    }

    fn stopped(&self) -> bool {
        self.stopped.load(Ordering::Relaxed)
    }

    fn send(&self, chunk: Chunk) {
        // A consumer that left has no use for the chunk.
        let _ = self.chunks.send(chunk);
    }
}
