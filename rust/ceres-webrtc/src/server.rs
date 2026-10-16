//! The media port and the sessions it serves.

use std::collections::HashMap;
use std::io;
use std::net::IpAddr;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::{Duration, Instant};

use ceres_config::ServerWebrtcConfig;
use ceres_media::{
    FrameOrder, LiveSource, MediaCodec, MediaError, MediaPacket, OwnedTrack, PacketItem,
    PacketStream, is_unreferenced,
};
use str0m::bwe::Bitrate;
use str0m::change::SdpOffer;
use str0m::crypto::CryptoProvider;
use str0m::net::{Protocol, Receive};
use str0m::{Input, Rtc, RtcConfig};
use tokio::sync::{Semaphore, mpsc, oneshot};

use crate::candidates::{candidates, local_addresses};
use crate::delivery::REPORT_INTERVAL;
use crate::picture::Picture;
use crate::session::{Session, SessionId, offered_video};
use crate::socket::{MediaSocket, MediaSockets, ReceiveBuffers};

/// What a session does with a source whose frames arrive out of display order, as B-frames
/// make them. A browser shows WebRTC frames in the order they arrive, so sending them as they
/// come plays the picture back and forth.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum ReorderedFrames {
    /// Refuses the source, so the browser plays it over HTTP at its full frame rate.
    #[default]
    Refuse,
    /// Drops the frames nothing references, sending the rest in display order at a lower
    /// frame rate, and refuses a source whose kept frames still reorder.
    Drop,
}

/// How long a new session waits for the source's first picture before giving up.
///
/// It is fixed, since a source's own stall timeout may be long or absent, and a browser
/// waiting this long falls back to the fragmented MP4 stream.
pub const OPEN_TRACK_TIMEOUT: Duration = Duration::from_secs(10);

/// How many source reads wait for the event loop, across every session.
const PACKET_BACKLOG: usize = 256;

/// The bandwidth a session's estimate starts from, above what most live video sends. Nothing
/// lowers a source's rate to fit, so an estimate starting under it holds the first seconds back.
const INITIAL_ESTIMATE: Bitrate = Bitrate::mbps(20);

/// The packets a session keeps for the browser to ask for again and for the pacer to hold,
/// about four seconds of 10 Mbit/s video. str0m's default of 1000 is a second of it, less than
/// the two seconds the pacer may queue.
const SEND_BUFFER_PACKETS: usize = 4096;

/// Why a session could not open.
#[derive(Debug, thiserror::Error)]
pub enum WebrtcError {
    #[error("every WebRTC session is taken")]
    Full,
    #[error("the SDP offer was refused: {0}")]
    Offer(String),
    #[error("{0}")]
    Codec(String),
    #[error("the source failed: {0}")]
    Source(String),
    #[error("the source sent no picture within {OPEN_TRACK_TIMEOUT:?}")]
    Timeout,
    #[error("the source sends its frames out of display order")]
    Reordered,
}

/// A session just opened.
#[derive(Debug)]
pub struct WebrtcAnswer {
    /// The ID that closes the session.
    pub id: String,
    /// The SDP answer to the browser's offer.
    pub sdp: String,
    /// Resolves once the session ends, for whatever reason.
    pub closed: oneshot::Receiver<()>,
}

/// The media port, serving live sources to browsers over WebRTC.
///
/// Dropping the server ends every session and closes the port.
pub struct WebrtcServer {
    commands: mpsc::Sender<Command>,
    slots: Arc<Semaphore>,
    crypto: Arc<CryptoProvider>,
    hosts: Vec<IpAddr>,
    port: u16,
    no_ice_timeout: Duration,
    /// The addresses of the sockets still serving, which bound the candidates offered. The
    /// event loop drops a socket's address when it fails.
    receiving: Arc<Mutex<Vec<IpAddr>>>,
}

enum Command {
    Open(Box<Session>),
    Close {
        id: String,
        closed: oneshot::Sender<bool>,
    },
}

impl WebrtcServer {
    /// Binds the media port at `address`, the server's `bind`, and starts serving it.
    ///
    /// Must be called within a Tokio runtime.
    pub fn bind(address: IpAddr, config: &ServerWebrtcConfig) -> io::Result<Self> {
        let sockets = MediaSockets::bind(address, config.port)?;
        let port = sockets.port();
        let receiving = Arc::new(Mutex::new(sockets.addresses().collect()));
        let max_sessions = usize::try_from(config.max_sessions).unwrap_or(usize::MAX);
        let (commands, receiver) = mpsc::channel(max_sessions.min(64));
        let event_loop = EventLoop::new(sockets, Arc::clone(&receiving), max_sessions);
        tokio::spawn(event_loop.run(receiver));
        log::info!("WebRTC media is served on UDP port {port}");
        Ok(Self {
            commands,
            slots: Arc::new(Semaphore::new(max_sessions.min(Semaphore::MAX_PERMITS))),
            crypto: Arc::new(str0m::crypto::from_feature_flags()),
            hosts: config.hosts.clone(),
            port,
            no_ice_timeout: config.no_ice_timeout.duration(),
            receiving,
        })
    }

    /// The UDP port media is served on.
    pub fn port(&self) -> u16 {
        self.port
    }

    /// Opens a session sending `source` to the browser that made `offer`, once the source has
    /// its first picture and its frames have shown which order they come in, handling
    /// reordered ones as `reordered` says.
    pub async fn open(
        &self,
        source: LiveSource,
        offer: &str,
        reordered: ReorderedFrames,
    ) -> Result<WebrtcAnswer, WebrtcError> {
        let slot = Arc::clone(&self.slots)
            .try_acquire_owned()
            .map_err(|_| WebrtcError::Full)?;
        let offer = SdpOffer::from_sdp_string(offer)
            .map_err(|error| WebrtcError::Offer(error.to_string()))?;
        let sendable = [MediaCodec::H264, MediaCodec::H265];
        if !sendable
            .iter()
            .any(|codec| offered_video(&offer, *codec).is_some())
        {
            return Err(WebrtcError::Codec(
                "the offer has no H.264 or H.265 video to answer".into(),
            ));
        }
        let options = source.options();
        let stream = PacketStream::shared(source.key(), || source.connection(), options);
        let stream = Arc::new(stream);
        let dropping = reordered == ReorderedFrames::Drop;
        let mut picture = first_picture(&stream, dropping).await?;
        let track = Arc::clone(&picture.track);
        let codec = track.codec();
        if !sendable.contains(&codec) {
            return Err(WebrtcError::Codec(
                "the source's video is neither H.264 nor H.265".into(),
            ));
        }
        // A browser offers only the codecs it can decode, so one without the source's plays
        // it over HTTP instead.
        let Some(mid) = offered_video(&offer, codec) else {
            return Err(WebrtcError::Codec(format!(
                "the offer cannot receive the source's {codec:?} video"
            )));
        };
        if picture.order == FrameOrder::Reordered {
            return Err(WebrtcError::Reordered);
        }

        let mut rtc = self.rtc(codec);
        let local = local_addresses();
        let offered = {
            let receiving = self
                .receiving
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            candidates(self.port, &local, &self.hosts, &receiving)
        };
        for candidate in offered {
            rtc.add_local_candidate(candidate);
        }
        let answer = rtc
            .sdp_api()
            .accept_offer(offer)
            .map_err(|error| WebrtcError::Offer(error.to_string()))?;
        let id = uuid::Uuid::new_v4().to_string();
        let (mut session, closed) = Session::new(
            id.as_str().into(),
            rtc,
            mid,
            stream,
            track,
            dropping,
            slot,
            self.no_ice_timeout,
        )?;
        // Held for the browser to start from, as the packets read after these will be.
        for packet in picture.packets.take() {
            if !session.feed(PacketItem::Packet(packet)) {
                return Err(WebrtcError::Reordered);
            }
        }
        // The event loop ends only with the server, which `self` keeps alive.
        let _ = self.commands.send(Command::Open(Box::new(session))).await;
        Ok(WebrtcAnswer {
            id,
            sdp: answer.to_sdp_string(),
            closed,
        })
    }

    /// Ends the session `id`, `false` when there is none.
    pub async fn close(&self, id: &str) -> bool {
        let (closed, receiver) = oneshot::channel();
        let command = Command::Close {
            id: id.to_owned(),
            closed,
        };
        self.commands.send(command).await.is_ok() && receiver.await.unwrap_or(false)
    }

    /// A connection answering with `codec` alone, the one the source sends.
    fn rtc(&self, codec: MediaCodec) -> Rtc {
        // The browser drives ICE, so the server answers its checks and sends none. The
        // bandwidth estimate drives the pacer, which spreads each keyframe's packets out so no
        // router on the path overflows.
        RtcConfig::new()
            .set_crypto_provider(Arc::clone(&self.crypto))
            .set_ice_lite(true)
            .clear_codecs()
            .enable_h264(codec == MediaCodec::H264)
            .enable_h265(codec == MediaCodec::H265)
            .enable_bwe(Some(INITIAL_ESTIMATE))
            .set_send_buffer_video(SEND_BUFFER_PACKETS)
            .set_stats_interval(Some(REPORT_INTERVAL))
            .build(Instant::now())
    }
}

/// A source's latest track and the packets of it read while telling the order of its frames.
struct FirstPicture {
    track: Arc<OwnedTrack>,
    /// The packets since `track`'s latest keyframe, for the session to start from.
    packets: Picture<MediaPacket>,
    /// The order of the frames a session sends, those a dropping one drops left out.
    order: FrameOrder,
}

/// Reads the stream's first track and then its packets until the order of the frames a
/// session sends shows, those it drops when `dropping` left out, and stops the stream if that
/// takes too long.
///
/// A stream joined partway through a source's group of pictures shows its order only after the
/// next keyframe, seconds away for many live sources, so only the packets a session would hold are.
async fn first_picture(
    stream: &Arc<PacketStream>,
    dropping: bool,
) -> Result<FirstPicture, WebrtcError> {
    let reading = Arc::clone(stream);
    let wait = tokio::task::spawn_blocking(move || {
        let read = || match reading.next() {
            Some(Ok(item)) => Ok(item),
            Some(Err(error)) => Err(WebrtcError::Source(error.to_string())),
            None => Err(WebrtcError::Source("the source ended".into())),
        };
        let order = || {
            if dropping {
                reading.referenced_frame_order()
            } else {
                reading.frame_order()
            }
        };
        let mut track = loop {
            // A notice comes before the picture when the source is slow to connect.
            if let PacketItem::Track(track) = read()? {
                break track;
            }
        };
        let mut packets = Picture::new(PacketStream::GOP_BYTES);
        while order() == FrameOrder::Unknown {
            match read()? {
                PacketItem::Track(next) => {
                    track = next;
                    packets.clear();
                }
                PacketItem::Packet(packet) => {
                    if !(dropping && is_unreferenced(packet.data(), track.codec())) {
                        packets.hold(packet);
                    }
                }
                PacketItem::Notice(_) => {}
            }
        }
        Ok(FirstPicture {
            track,
            packets,
            order: order(),
        })
    });
    match tokio::time::timeout(OPEN_TRACK_TIMEOUT, wait).await {
        Ok(Ok(picture)) => picture,
        Ok(Err(error)) => Err(WebrtcError::Source(error.to_string())),
        Err(_) => {
            stream.stop();
            Err(WebrtcError::Timeout)
        }
    }
}

/// One read from a session's source, `None` once it ends.
type SourceRead = (SessionId, Option<Result<PacketItem, MediaError>>);

/// The task owning the sockets and every session, so a datagram finds its session without a
/// lock.
struct EventLoop {
    sockets: MediaSockets,
    v4_buffers: Option<ReceiveBuffers>,
    v6_buffers: Option<ReceiveBuffers>,
    /// Shared with the server, which offers candidates only at these addresses.
    receiving: Arc<Mutex<Vec<IpAddr>>>,
    /// Bounded by the server's session slots.
    sessions: HashMap<SessionId, Session>,
    reads: mpsc::Sender<SourceRead>,
    reads_receiver: mpsc::Receiver<SourceRead>,
}

impl EventLoop {
    fn new(sockets: MediaSockets, receiving: Arc<Mutex<Vec<IpAddr>>>, max_sessions: usize) -> Self {
        let (reads, reads_receiver) = mpsc::channel(PACKET_BACKLOG);
        Self {
            v4_buffers: sockets.v4.as_ref().map(MediaSocket::buffers),
            v6_buffers: sockets.v6.as_ref().map(MediaSocket::buffers),
            receiving,
            sockets,
            sessions: HashMap::with_capacity(max_sessions.min(64)),
            reads,
            reads_receiver,
        }
    }

    async fn run(mut self, mut commands: mpsc::Receiver<Command>) {
        loop {
            let deadline = self.sessions.values().map(|session| session.timeout).min();
            tokio::select! {
                command = commands.recv() => match command {
                    Some(command) => self.command(command),
                    None => break,
                },
                Some((id, read)) = self.reads_receiver.recv() => self.read(&id, read),
                ready = readable(self.sockets.v4.as_ref()) => match ready {
                    Ok(()) => self.receive(false),
                    Err(error) => self.fail(false, &error),
                },
                ready = readable(self.sockets.v6.as_ref()) => match ready {
                    Ok(()) => self.receive(true),
                    Err(error) => self.fail(true, &error),
                },
                () = sleep_until(deadline) => self.timeouts(),
            }
            if self.sockets.v4.is_none() && self.sockets.v6.is_none() {
                log::error!("WebRTC media stopped, every socket failed");
                break;
            }
        }
        for (_, session) in self.sessions.drain() {
            session.close(&self.sockets);
        }
    }

    fn command(&mut self, command: Command) {
        match command {
            Command::Open(mut session) => {
                if session.drive(None, &self.sockets) {
                    self.spawn_reads(&session);
                    self.sessions.insert(Arc::clone(&session.id), *session);
                }
            }
            Command::Close { id, closed } => {
                let session = self.sessions.remove(id.as_str());
                let found = session.is_some();
                if let Some(session) = session {
                    session.close(&self.sockets);
                }
                let _ = closed.send(found);
            }
        }
    }

    /// Reads the session's source on a thread of its own, since a read blocks, and a full
    /// backlog blocks it, which the source drops a stream that falls behind for.
    fn spawn_reads(&self, session: &Session) {
        let stream = Arc::clone(&session.stream);
        let id = Arc::clone(&session.id);
        let reads = self.reads.clone();
        tokio::task::spawn_blocking(move || {
            loop {
                let read = stream.next();
                let last = !matches!(read, Some(Ok(_)));
                if reads.blocking_send((Arc::clone(&id), read)).is_err() || last {
                    return;
                }
            }
        });
    }

    fn read(&mut self, id: &SessionId, read: Option<Result<PacketItem, MediaError>>) {
        let Some(session) = self.sessions.get_mut(id) else {
            return;
        };
        let alive = match read {
            Some(Ok(item)) => session.feed(item) && session.drive(None, &self.sockets),
            Some(Err(error)) => {
                log::warn!("WebRTC session {id} lost its source: {error}");
                false
            }
            None => false,
        };
        if !alive {
            self.end(id);
        }
    }

    /// Drops the socket of one family, which stops offering its address.
    fn fail(&mut self, v6: bool, error: &io::Error) {
        let (socket, buffers) = if v6 {
            (self.sockets.v6.take(), &mut self.v6_buffers)
        } else {
            (self.sockets.v4.take(), &mut self.v4_buffers)
        };
        *buffers = None;
        let Some(socket) = socket else {
            return;
        };
        let address = socket.address();
        log::error!("WebRTC media at {address} stopped, its socket failed: {error}");
        self.receiving
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .retain(|receiving| *receiving != address);
    }

    fn receive(&mut self, v6: bool) {
        let Self {
            sockets,
            v4_buffers,
            v6_buffers,
            sessions,
            ..
        } = self;
        let (socket, buffers) = if v6 {
            (sockets.v6.as_ref(), v6_buffers.as_mut())
        } else {
            (sockets.v4.as_ref(), v4_buffers.as_mut())
        };
        let (Some(socket), Some(buffers)) = (socket, buffers) else {
            return;
        };
        let mut ended = Vec::new();
        socket.receive(buffers, |source, destination, datagram| {
            let Ok(contents) = datagram.try_into() else {
                return;
            };
            let receive = Receive {
                proto: Protocol::Udp,
                source,
                destination,
                contents,
            };
            let input = Input::Receive(Instant::now(), receive);
            // A linear scan, bounded by the session limit.
            let session = sessions
                .values_mut()
                .find(|session| session.rtc.accepts(&input));
            if let Some(session) = session
                && !session.drive(Some(input), sockets)
            {
                ended.push(Arc::clone(&session.id));
            }
        });
        for id in ended {
            self.end(&id);
        }
    }

    fn timeouts(&mut self) {
        let now = Instant::now();
        let mut ended = Vec::new();
        for session in self
            .sessions
            .values_mut()
            .filter(|session| session.timeout <= now)
        {
            if !session.drive(Some(Input::Timeout(now)), &self.sockets) {
                ended.push(Arc::clone(&session.id));
            }
        }
        for id in ended {
            self.end(&id);
        }
    }

    fn end(&mut self, id: &SessionId) {
        if let Some(session) = self.sessions.remove(id) {
            log::info!("WebRTC session {id} ended");
            session.close(&self.sockets);
        }
    }
}

async fn readable(socket: Option<&MediaSocket>) -> io::Result<()> {
    match socket {
        Some(socket) => socket.readable().await,
        None => std::future::pending().await,
    }
}

async fn sleep_until(deadline: Option<Instant>) {
    match deadline {
        Some(deadline) => tokio::time::sleep_until(deadline.into()).await,
        None => std::future::pending().await,
    }
}
