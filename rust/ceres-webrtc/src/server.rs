//! The media port and the sessions it serves.

use std::collections::HashMap;
use std::io;
use std::net::IpAddr;
use std::sync::Arc;
use std::time::{Duration, Instant};

use ceres_config::ServerWebrtcConfig;
use ceres_media::{LiveSource, MediaCodec, MediaError, OwnedTrack, PacketItem, PacketStream};
use str0m::change::SdpOffer;
use str0m::crypto::CryptoProvider;
use str0m::net::{Protocol, Receive};
use str0m::{Input, Rtc, RtcConfig};
use tokio::sync::{Semaphore, mpsc, oneshot};

use crate::candidates::{candidates, local_addresses};
use crate::session::{Session, SessionId, offered_video};
use crate::socket::{MediaSocket, MediaSockets, ReceiveBuffers};

/// How long a new session waits for the source's first picture before giving up.
///
/// It is fixed, since a source's own stall timeout may be long or absent, and a browser
/// waiting this long falls back to the fragmented MP4 stream.
pub const OPEN_TRACK_TIMEOUT: Duration = Duration::from_secs(10);

/// How many source reads wait for the event loop, across every session.
const PACKET_BACKLOG: usize = 256;

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
}

/// A session just opened.
#[derive(Debug)]
pub struct WebrtcAnswer {
    /// The ID that closes the session.
    pub id: String,
    /// The SDP answer to the browser's offer.
    pub sdp: String,
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
    /// Whether the port has an IPv6 socket, without which IPv6 candidates reach nothing.
    v6: bool,
}

enum Command {
    Open(Box<Session>),
    Close {
        id: String,
        closed: oneshot::Sender<bool>,
    },
}

impl WebrtcServer {
    /// Binds the media port and starts serving it.
    ///
    /// Must be called within a Tokio runtime.
    pub fn bind(config: &ServerWebrtcConfig) -> io::Result<Self> {
        let sockets = MediaSockets::bind(config.port)?;
        let port = sockets.port();
        let v6 = sockets.v6.is_some();
        let max_sessions = usize::try_from(config.max_sessions).unwrap_or(usize::MAX);
        let (commands, receiver) = mpsc::channel(max_sessions.min(64));
        tokio::spawn(EventLoop::new(sockets, max_sessions).run(receiver));
        log::info!("WebRTC media is served on UDP port {port}");
        Ok(Self {
            commands,
            slots: Arc::new(Semaphore::new(max_sessions.min(Semaphore::MAX_PERMITS))),
            crypto: Arc::new(str0m::crypto::from_feature_flags()),
            hosts: config.hosts.clone(),
            port,
            v6,
        })
    }

    /// The UDP port media is served on.
    pub fn port(&self) -> u16 {
        self.port
    }

    /// Opens a session sending `source` to the browser that made `offer`, once the source has
    /// its first picture.
    pub async fn open(&self, source: LiveSource, offer: &str) -> Result<WebrtcAnswer, WebrtcError> {
        let slot = Arc::clone(&self.slots)
            .try_acquire_owned()
            .map_err(|_| WebrtcError::Full)?;
        let offer = SdpOffer::from_sdp_string(offer)
            .map_err(|error| WebrtcError::Offer(error.to_string()))?;
        let Some(mid) = offered_video(&offer) else {
            return Err(WebrtcError::Codec(
                "the offer has no H.264 video to answer".into(),
            ));
        };
        let options = source.options();
        let stream = PacketStream::shared(source.key(), || source.connection(), options);
        let stream = Arc::new(stream);
        let track = first_track(&stream).await?;
        if track.codec() != MediaCodec::H264 {
            let codec = track.codec();
            return Err(WebrtcError::Codec(format!(
                "{codec:?} video cannot be sent over WebRTC"
            )));
        }

        let mut rtc = self.rtc();
        for candidate in candidates(self.port, &local_addresses(), &self.hosts, self.v6) {
            rtc.add_local_candidate(candidate);
        }
        let answer = rtc
            .sdp_api()
            .accept_offer(offer)
            .map_err(|error| WebrtcError::Offer(error.to_string()))?;
        let id = uuid::Uuid::new_v4().to_string();
        let Some(session) = Session::new(id.as_str().into(), rtc, mid, stream, track, slot) else {
            return Err(WebrtcError::Codec(
                "the offer has no H.264 video to answer".into(),
            ));
        };
        // The event loop ends only with the server, which `self` keeps alive.
        let _ = self.commands.send(Command::Open(Box::new(session))).await;
        Ok(WebrtcAnswer {
            id,
            sdp: answer.to_sdp_string(),
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

    fn rtc(&self) -> Rtc {
        // The browser drives ICE, so the server answers its checks and sends none.
        RtcConfig::new()
            .set_crypto_provider(Arc::clone(&self.crypto))
            .set_ice_lite(true)
            .clear_codecs()
            .enable_h264(true)
            .build(Instant::now())
    }
}

/// Waits for the stream's first track, stopping the stream if it does not come.
async fn first_track(stream: &Arc<PacketStream>) -> Result<Arc<OwnedTrack>, WebrtcError> {
    let reading = Arc::clone(stream);
    let wait = tokio::task::spawn_blocking(move || {
        loop {
            match reading.next() {
                Some(Ok(PacketItem::Track(track))) => return Ok(track),
                // A notice comes before the picture when the source is slow to connect.
                Some(Ok(_)) => {}
                Some(Err(error)) => return Err(WebrtcError::Source(error.to_string())),
                None => return Err(WebrtcError::Source("the source ended".into())),
            }
        }
    });
    match tokio::time::timeout(OPEN_TRACK_TIMEOUT, wait).await {
        Ok(Ok(track)) => track,
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
    v4_buffers: ReceiveBuffers,
    v6_buffers: Option<ReceiveBuffers>,
    /// Bounded by the server's session slots.
    sessions: HashMap<SessionId, Session>,
    reads: mpsc::Sender<SourceRead>,
    reads_receiver: mpsc::Receiver<SourceRead>,
}

impl EventLoop {
    fn new(sockets: MediaSockets, max_sessions: usize) -> Self {
        let (reads, reads_receiver) = mpsc::channel(PACKET_BACKLOG);
        Self {
            v4_buffers: sockets.v4.buffers(),
            v6_buffers: sockets.v6.as_ref().map(MediaSocket::buffers),
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
                ready = self.sockets.v4.readable() => match ready {
                    Ok(()) => self.receive(false),
                    Err(error) => {
                        log::error!("WebRTC media stopped, its IPv4 socket failed: {error}");
                        break;
                    }
                },
                ready = readable(self.sockets.v6.as_ref()) => match ready {
                    Ok(()) => self.receive(true),
                    Err(error) => {
                        log::error!("WebRTC media over IPv6 stopped, its socket failed: {error}");
                        self.sockets.v6 = None;
                        self.v6_buffers = None;
                    }
                },
                () = sleep_until(deadline) => self.timeouts(),
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

    fn receive(&mut self, v6: bool) {
        let Self {
            sockets,
            v4_buffers,
            v6_buffers,
            sessions,
            ..
        } = self;
        let (socket, buffers) = match (v6, sockets.v6.as_ref(), v6_buffers.as_mut()) {
            (false, ..) => (&sockets.v4, v4_buffers),
            (true, Some(socket), Some(buffers)) => (socket, buffers),
            (true, ..) => return,
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
