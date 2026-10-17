//! One browser's connection, fed the packets of one live source.

use std::sync::Arc;
use std::time::{Duration, Instant};

use ceres_media::{
    FrameOrder, MediaCodec, MediaPacket, OwnedTrack, PacketItem, PacketStream, is_unreferenced,
};
use str0m::change::SdpOffer;
use str0m::format::{Codec, PayloadParams};
use str0m::media::{Direction, MediaTime, Mid, Pt};
use str0m::stats::MediaEgressStats;
use str0m::{Event, IceConnectionState, Input, Output, Rtc};
use tokio::sync::{OwnedSemaphorePermit, oneshot};

use crate::WebrtcError;
use crate::delivery::Delivery;
use crate::parameter_sets::with_parameter_sets;
use crate::picture::Picture;
use crate::server::SEND_BUFFER_PACKETS;
use crate::socket::MediaSockets;

/// The most outputs one input may produce before the session is ended, since every session
/// shares one task and a session that never reaches its timeout would stall the rest.
///
/// A large keyframe packetizes to a few hundred datagrams, well under it.
const MAX_OUTPUTS: usize = 8192;

/// The oldest packet a session resends, str0m's own default, which it keeps private.
const RESEND_AGE: Duration = Duration::from_secs(3);

/// The share of resends past which str0m stops resending, its own default too.
const RESEND_RATIO_CAP: Option<f32> = Some(0.15);

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
    /// str0m sends media written before then late.
    pending: Picture<MediaPacket>,
    /// Whether packets are skipped until a keyframe is sent, as they are after the track
    /// changes, since a picture can start only there.
    awaiting_key: bool,
    /// Whether frames nothing references are dropped, so the rest go out in display order. A
    /// source whose kept frames reorder too ends the session.
    dropping: bool,
    delivery: Delivery,
    _slot: OwnedSemaphorePermit,
    /// Dropped with the session, which resolves the receiver the server's caller holds.
    _ended: oneshot::Sender<()>,
}

impl Session {
    /// Returns a session sending `track` over the `mid` video `rtc` answered, and a receiver
    /// resolving once the session ends.
    ///
    /// `dropping` drops the frames nothing references, rather than sending every frame.
    #[expect(
        clippy::too_many_arguments,
        reason = "each is a separate part the server negotiated"
    )]
    pub(crate) fn new(
        id: SessionId,
        mut rtc: Rtc,
        mid: Mid,
        stream: Arc<PacketStream>,
        track: Arc<OwnedTrack>,
        dropping: bool,
        slot: OwnedSemaphorePermit,
        no_ice_timeout: Duration,
    ) -> Result<(Self, oneshot::Receiver<()>), WebrtcError> {
        let codec = track.codec();
        let pt = rtc
            .writer(mid)
            .and_then(|writer| {
                let mut params = writer.payload_params();
                params
                    .find(|params| is_sendable(params, codec))
                    .map(PayloadParams::pt)
            })
            .ok_or_else(|| {
                WebrtcError::Codec(format!("the answer agreed on no {codec:?} payload"))
            })?;
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
            pending: Picture::new(PacketStream::GOP_BYTES),
            awaiting_key: true,
            dropping,
            delivery: Delivery::new(now),
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
                    let sent =
                        sockets.send(transmit.source, transmit.destination, &transmit.contents);
                    if !sent && self.delivery.drop_datagram() {
                        log::warn!(
                            "WebRTC session {} is losing packets before they leave this host, \
                             which sends media faster than its network takes it",
                            self.id
                        );
                    }
                }
                Ok(Output::Event(Event::MediaEgressStats(stats))) => self.report(&stats),
                Ok(Output::Event(Event::Connected)) => {
                    log::info!("WebRTC session {} connected", self.id);
                    self.connected = true;
                    for packet in self.pending.take() {
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
            PacketItem::Track(track) if track.codec() != self.track.codec() => {
                log::warn!("WebRTC session {} ended, the source changed codec", self.id);
                return false;
            }
            PacketItem::Track(track) => {
                self.track = track;
                self.awaiting_key = true;
                self.pending.clear();
            }
            PacketItem::Packet(packet) => {
                // Dropped before it is held too, or the first picture would play choppy.
                if self.dropping && is_unreferenced(packet.data(), self.track.codec()) {
                    return true;
                }
                // A source can start reordering partway, after its encoder settings change or
                // a reconnect to another device at the same address, and a browser shows
                // frames in the order they arrive. Ending lets the console fall back to HTTP.
                let order = if self.dropping {
                    self.stream.referenced_frame_order()
                } else {
                    self.stream.frame_order()
                };
                if order == FrameOrder::Reordered {
                    log::info!(
                        "WebRTC session {} ended, its source reorders the frames it sends",
                        self.id
                    );
                    return false;
                }
                if self.connected {
                    self.write(&packet);
                } else {
                    self.pending.hold(packet);
                }
            }
            PacketItem::Notice(notice) => log::debug!("WebRTC session {}: {notice:?}", self.id),
        }
        true
    }

    fn write(&mut self, packet: &MediaPacket) {
        if self.awaiting_key && !packet.is_key() {
            return;
        }
        let Some(pts) = packet.timing().pts else {
            return;
        };
        let data = with_parameter_sets(
            packet.data(),
            self.track.extradata(),
            self.track.codec(),
            packet.is_key(),
        );
        let time = MediaTime::from_90khz(pts.max(0).unsigned_abs());
        let Some(writer) = self.rtc.writer(self.mid) else {
            return;
        };
        match writer.write(self.pt, Instant::now(), time, data) {
            Ok(()) => self.awaiting_key = false,
            Err(error) => log::warn!("Writing to WebRTC session {} failed: {error}", self.id),
        }
    }

    /// Writes nothing more until the source's next keyframe and forgets the packets it sent,
    /// since the socket dropped them and a resend would deliver the stretch late.
    pub(crate) fn skip_to_key(&mut self) {
        self.awaiting_key = true;
        self.pending.clear();
        if let Some(stream) = self.rtc.direct_api().stream_tx_by_mid(self.mid, None) {
            stream.set_rtx_cache(SEND_BUFFER_PACKETS, RESEND_AGE, RESEND_RATIO_CAP);
        }
    }

    /// Logs the loss since the last report.
    fn report(&mut self, stats: &MediaEgressStats) {
        let report = self.delivery.report(stats);
        if report.lost > 0 || report.nacks > 0 {
            log::debug!(
                "WebRTC session {}: sent {} packets, the browser lost {} and asked for {} again",
                self.id,
                report.sent,
                report.lost,
                report.nacks
            );
        }
    }

    /// Tells the browser the session is over.
    pub(crate) fn close(mut self, sockets: &MediaSockets) {
        log::info!(
            "WebRTC session {} {}",
            self.id,
            self.delivery.summary(Instant::now())
        );
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

/// Returns the first media in `offer` that would receive `codec` video.
///
/// str0m reports media only once DTLS is up, so the offer is the one place to learn it in time
/// to refuse a browser that cannot play the source.
pub(crate) fn offered_video(offer: &SdpOffer, codec: MediaCodec) -> Option<Mid> {
    let line = offer.media_lines.iter().find(|line| {
        let receives = matches!(line.direction(), Direction::RecvOnly | Direction::SendRecv);
        let params = line.rtp_params();
        !line.disabled && receives && params.iter().any(|params| is_sendable(params, codec))
    })?;
    Some(line.mid())
}

/// Whether `params` is `codec` as its packetizer writes it. H.264 must be fragmented, which is
/// mode 1, and H.265 has only the one mode.
fn is_sendable(params: &PayloadParams, codec: MediaCodec) -> bool {
    let spec = params.spec();
    match codec {
        MediaCodec::H264 => spec.codec == Codec::H264 && spec.format.packetization_mode == Some(1),
        MediaCodec::H265 => spec.codec == Codec::H265,
        MediaCodec::Other => false,
    }
}
