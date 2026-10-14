//! One browser's connection, fed the packets of one live source.

use std::sync::Arc;
use std::time::{Duration, Instant};

use ceres_media::{MediaCodec, MediaPacket, OwnedTrack, PacketItem, PacketStream};
use str0m::change::SdpOffer;
use str0m::format::{Codec, PayloadParams};
use str0m::media::{Direction, MediaTime, Mid, Pt};
use str0m::{Event, IceConnectionState, Input, Output, Rtc};
use tokio::sync::{OwnedSemaphorePermit, oneshot};

use crate::WebrtcError;
use crate::h264::with_parameter_sets;
use crate::socket::MediaSockets;

/// The most outputs one input may produce before the session is ended, since every session
/// shares one task and a session that never reaches its timeout would stall the rest.
///
/// A large keyframe packetizes to a few hundred datagrams, well under it.
const MAX_OUTPUTS: usize = 8192;

/// A session's ID, shared with the thread reading its packets.
pub(crate) type SessionId = Arc<str>;

pub(crate) struct Session {
    pub(crate) id: SessionId,
    pub(crate) rtc: Rtc,
    pub(crate) stream: Arc<PacketStream>,
    mid: Mid,
    pt: Pt,
    track: Arc<OwnedTrack>,
    /// When str0m next expects a timeout input.
    pub(crate) timeout: Instant,
    /// When the session ends unless its browser has connected, since a browser that never
    /// does holds a slot and a source connection until then.
    connect_by: Instant,
    connected: bool,
    /// The packets since the source's last keyframe, held until the browser connects, since
    /// str0m sends media written before then late and the picture can start only at a keyframe.
    pending: Vec<MediaPacket>,
    /// The bytes in `pending`, bounded by `PacketStream::GOP_BYTES`.
    pending_bytes: usize,
    /// Whether packets are skipped until a keyframe is sent, as they are after the track
    /// changes, since a picture can start only there.
    awaiting_key: bool,
    _slot: OwnedSemaphorePermit,
    /// Dropped with the session, which resolves the receiver the server's caller holds.
    _ended: oneshot::Sender<()>,
}

impl Session {
    /// Returns a session sending `track` over the `mid` video `rtc` answered, and a receiver
    /// resolving once the session ends.
    pub(crate) fn new(
        id: SessionId,
        mut rtc: Rtc,
        mid: Mid,
        stream: Arc<PacketStream>,
        track: Arc<OwnedTrack>,
        slot: OwnedSemaphorePermit,
        no_ice_timeout: Duration,
    ) -> Result<(Self, oneshot::Receiver<()>), WebrtcError> {
        let pt = rtc
            .writer(mid)
            .and_then(|writer| {
                let mut params = writer.payload_params();
                params
                    .find(|params| is_sendable(params))
                    .map(PayloadParams::pt)
            })
            .ok_or_else(|| WebrtcError::Codec("the answer agreed on no H.264 payload".into()))?;
        let (ended, closed) = oneshot::channel();
        let now = Instant::now();
        let session = Self {
            id,
            rtc,
            stream,
            mid,
            pt,
            track,
            timeout: now,
            connect_by: now + no_ice_timeout,
            connected: false,
            pending: Vec::new(),
            pending_bytes: 0,
            awaiting_key: true,
            _slot: slot,
            _ended: ended,
        };
        Ok((session, closed))
    }

    /// Hands str0m whatever is due and sends what it returns, `false` once the session is over.
    pub(crate) fn drive(&mut self, input: Option<Input<'_>>, sockets: &MediaSockets) -> bool {
        if let Some(input) = input
            && let Err(error) = self.rtc.handle_input(input)
        {
            log::warn!("WebRTC session {} failed: {error}", self.id);
            return false;
        }
        if !self.connected && Instant::now() >= self.connect_by {
            log::info!(
                "WebRTC session {} ended, its browser did not connect in time",
                self.id
            );
            return false;
        }
        for _ in 0..MAX_OUTPUTS {
            match self.rtc.poll_output() {
                Ok(Output::Timeout(timeout)) => {
                    self.timeout = if self.connected {
                        timeout
                    } else {
                        timeout.min(self.connect_by)
                    };
                    return self.rtc.is_alive();
                }
                Ok(Output::Transmit(transmit)) => {
                    sockets.send(transmit.source, transmit.destination, &transmit.contents);
                }
                Ok(Output::Event(Event::Connected)) => {
                    log::info!("WebRTC session {} connected", self.id);
                    self.connected = true;
                    self.pending_bytes = 0;
                    for packet in std::mem::take(&mut self.pending) {
                        self.write(&packet);
                    }
                }
                Ok(Output::Event(Event::IceConnectionStateChange(
                    IceConnectionState::Disconnected,
                ))) => {
                    log::info!("WebRTC session {} disconnected", self.id);
                    return false;
                }
                Ok(Output::Event(_)) => {}
                Err(error) => {
                    log::warn!("WebRTC session {} failed: {error}", self.id);
                    return false;
                }
            }
        }
        log::warn!(
            "WebRTC session {} ended, it produced over {MAX_OUTPUTS} outputs",
            self.id
        );
        false
    }

    /// Takes one read of the source, `false` when it ended the session.
    pub(crate) fn feed(&mut self, item: PacketItem) -> bool {
        match item {
            PacketItem::Track(track) if track.codec() != MediaCodec::H264 => {
                log::warn!("WebRTC session {} ended, the source changed codec", self.id);
                return false;
            }
            PacketItem::Track(track) => {
                self.track = track;
                self.awaiting_key = true;
                self.pending.clear();
                self.pending_bytes = 0;
            }
            PacketItem::Packet(packet) if self.connected => self.write(&packet),
            PacketItem::Packet(packet) => self.hold(packet),
            PacketItem::Notice(notice) => log::debug!("WebRTC session {}: {notice:?}", self.id),
        }
        true
    }

    /// Keeps `packet` for the browser to start from once it connects.
    fn hold(&mut self, packet: MediaPacket) {
        if packet.is_key() {
            self.pending.clear();
            self.pending_bytes = 0;
        } else if self.pending.is_empty() {
            return;
        }
        self.pending_bytes += packet.data().len();
        if self.pending_bytes > PacketStream::GOP_BYTES {
            // The picture is too long to hold, so the browser starts at the next keyframe.
            self.pending.clear();
            self.pending_bytes = 0;
            return;
        }
        self.pending.push(packet);
    }

    fn write(&mut self, packet: &MediaPacket) {
        if self.awaiting_key && !packet.is_key() {
            return;
        }
        let Some(pts) = packet.timing().pts else {
            return;
        };
        let data = with_parameter_sets(packet.data(), self.track.extradata(), packet.is_key());
        let time = MediaTime::from_90khz(pts.max(0).unsigned_abs());
        let Some(writer) = self.rtc.writer(self.mid) else {
            return;
        };
        match writer.write(self.pt, Instant::now(), time, data) {
            Ok(()) => self.awaiting_key = false,
            Err(error) => log::warn!("Writing to WebRTC session {} failed: {error}", self.id),
        }
    }

    /// Tells the browser the session is over.
    pub(crate) fn close(mut self, sockets: &MediaSockets) {
        self.rtc.disconnect();
        self.drive(None, sockets);
    }
}

/// The thread reading the session's packets holds the stream too, so the session stops it
/// here, or that thread and the source connection outlive it.
impl Drop for Session {
    fn drop(&mut self) {
        self.stream.stop();
    }
}

/// Returns the first media in `offer` that would receive H.264 video.
///
/// str0m reports media only once DTLS is up, so the offer is the one place to learn it in time
/// to refuse a browser that cannot play the source.
pub(crate) fn offered_video(offer: &SdpOffer) -> Option<Mid> {
    let line = offer.media_lines.iter().find(|line| {
        let receives = matches!(line.direction(), Direction::RecvOnly | Direction::SendRecv);
        !line.disabled && receives && line.rtp_params().iter().any(is_sendable)
    })?;
    Some(line.mid())
}

/// Whether `params` is H.264 as the packetizer writes it, fragmented, which is mode 1.
fn is_sendable(params: &PayloadParams) -> bool {
    let spec = params.spec();
    spec.codec == Codec::H264 && spec.format.packetization_mode == Some(1)
}
