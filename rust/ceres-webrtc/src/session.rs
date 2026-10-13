//! One browser's connection, fed the packets of one live source.

use std::sync::Arc;
use std::time::Instant;

use ceres_media::{MediaCodec, MediaPacket, OwnedTrack, PacketItem, PacketStream};
use str0m::change::SdpOffer;
use str0m::format::{Codec, PayloadParams};
use str0m::media::{Direction, MediaTime, Mid, Pt};
use str0m::{Event, IceConnectionState, Input, Output, Rtc};
use tokio::sync::OwnedSemaphorePermit;

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
    connected: bool,
    /// Whether packets are skipped until a keyframe, as they are before the browser connects,
    /// since a picture can start only there.
    awaiting_key: bool,
    _slot: OwnedSemaphorePermit,
}

impl Session {
    /// Returns a session sending `track` over the `mid` video `rtc` answered, or `None` when the
    /// answer agreed on no H.264 to send it as.
    pub(crate) fn new(
        id: SessionId,
        mut rtc: Rtc,
        mid: Mid,
        stream: Arc<PacketStream>,
        track: Arc<OwnedTrack>,
        slot: OwnedSemaphorePermit,
    ) -> Option<Self> {
        let pt = rtc
            .writer(mid)?
            .payload_params()
            .find(|params| is_sendable(params))?
            .pt();
        Some(Self {
            id,
            rtc,
            stream,
            mid,
            pt,
            track,
            timeout: Instant::now(),
            connected: false,
            awaiting_key: true,
            _slot: slot,
        })
    }

    /// Hands str0m whatever is due and sends what it returns, `false` once the session is over.
    pub(crate) fn drive(&mut self, input: Option<Input<'_>>, sockets: &MediaSockets) -> bool {
        if let Some(input) = input
            && let Err(error) = self.rtc.handle_input(input)
        {
            log::warn!("WebRTC session {} failed: {error}", self.id);
            return false;
        }
        for _ in 0..MAX_OUTPUTS {
            match self.rtc.poll_output() {
                Ok(Output::Timeout(timeout)) => {
                    self.timeout = timeout;
                    return self.rtc.is_alive();
                }
                Ok(Output::Transmit(transmit)) => {
                    sockets.send(transmit.source, transmit.destination, &transmit.contents);
                }
                Ok(Output::Event(Event::Connected)) => {
                    log::info!("WebRTC session {} connected", self.id);
                    self.connected = true;
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
            }
            PacketItem::Packet(packet) => self.write(&packet),
            PacketItem::Notice(notice) => log::debug!("WebRTC session {}: {notice:?}", self.id),
        }
        true
    }

    fn write(&mut self, packet: &MediaPacket) {
        // str0m queues media written before the browser connects and sends it late, so writing
        // waits for the connection and then a keyframe.
        if !self.connected || self.awaiting_key && !packet.is_key() {
            return;
        }
        self.awaiting_key = false;
        let Some(pts) = packet.timing().pts else {
            return;
        };
        let data = with_parameter_sets(packet.data(), self.track.extradata(), packet.is_key());
        let time = MediaTime::from_90khz(pts.max(0).unsigned_abs());
        let Some(writer) = self.rtc.writer(self.mid) else {
            return;
        };
        if let Err(error) = writer.write(self.pt, Instant::now(), time, data) {
            log::warn!("Writing to WebRTC session {} failed: {error}", self.id);
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
