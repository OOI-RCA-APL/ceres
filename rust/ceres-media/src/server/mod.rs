//! A test RTSP server streaming clips over interleaved TCP, with network faults on demand.

mod session;
mod stream;

use std::net::{Shutdown, SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, PoisonError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use std::{fs, io};

use tempfile::TempDir;

use crate::MediaInput;

/// The clips built into the server, by the name `RtspServerOptions::clips` takes.
pub const RTSP_CLIPS: [(&str, &[u8]); 2] = [
    ("h264", include_bytes!("../../clips/h264.mp4")),
    ("h265", include_bytes!("../../clips/h265.mp4")),
];

/// How often the accept loop and a paced stream check for a stop or a due fault.
const POLL: Duration = Duration::from_millis(20);

/// What an `RtspServer` streams and the faults it injects.
#[derive(Debug, Clone)]
pub struct RtspServerOptions {
    /// Built-in clip names or file paths, played by successive sessions in turn.
    pub clips: Vec<String>,
    /// The URL path clients request.
    pub path: String,
    /// Closes each session this long after it starts playing.
    pub drop_after: Option<Duration>,
    /// Stops sending media this long after each session starts playing, keeping it open.
    pub stall_after: Option<Duration>,
    /// Closes this many connections as soon as they are accepted.
    pub refuse: usize,
    /// Closes the listener and every session each time the server has been up this long.
    pub restart_after: Option<Duration>,
    /// How long the server stays down on a restart.
    pub restart_downtime: Duration,
}

impl Default for RtspServerOptions {
    fn default() -> Self {
        Self {
            clips: vec![RTSP_CLIPS[0].0.to_owned()],
            path: "stream".to_owned(),
            drop_after: None,
            stall_after: None,
            refuse: 0,
            restart_after: None,
            restart_downtime: Duration::from_secs(1),
        }
    }
}

/// A running test RTSP server, stopped when dropped.
pub struct RtspServer {
    address: SocketAddr,
    shared: Arc<Shared>,
    thread: Option<JoinHandle<()>>,
    // Holds the built-in clips on disk while the server reads them.
    _clips: TempDir,
}

impl RtspServer {
    /// Binds `address`, port 0 for any free port, and starts serving on a background thread.
    pub fn start(address: SocketAddr, options: RtspServerOptions) -> io::Result<Self> {
        let directory = tempfile::tempdir()?;
        let clips = options
            .clips
            .iter()
            .map(|clip| resolve(clip, directory.path()))
            .collect::<io::Result<Vec<_>>>()?;
        if clips.is_empty() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "no clips to stream",
            ));
        }
        let listener = TcpListener::bind(address)?;
        listener.set_nonblocking(true)?;
        let address = listener.local_addr()?;
        let shared = Arc::new(Shared {
            clips,
            path: options.path.trim_matches('/').to_owned(),
            faults: StreamFaults {
                drop_after: options.drop_after,
                stall_after: options.stall_after,
            },
            stop: AtomicBool::new(false),
            sessions: AtomicU64::new(0),
            live: Mutex::new(Vec::new()),
        });
        let accept = Accept {
            shared: Arc::clone(&shared),
            address,
            refuse: options.refuse,
            restart: options
                .restart_after
                .map(|after| (after, options.restart_downtime)),
        };
        let thread = thread::Builder::new()
            .name("rtsp-server".to_owned())
            .spawn(move || accept.run(listener))?;
        Ok(Self {
            address,
            shared,
            thread: Some(thread),
            _clips: directory,
        })
    }

    pub fn address(&self) -> SocketAddr {
        self.address
    }

    /// The URL clients open.
    pub fn url(&self) -> String {
        format!("rtsp://{}/{}", self.address, self.shared.path)
    }

    /// Blocks until the server stops, which only a failing accept loop causes.
    pub fn wait(mut self) {
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

impl Drop for RtspServer {
    fn drop(&mut self) {
        self.shared.stop.store(true, Ordering::Relaxed);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

/// Writes a built-in clip into `directory` or takes `clip` as a path, then checks it has video.
fn resolve(clip: &str, directory: &Path) -> io::Result<PathBuf> {
    let path = match RTSP_CLIPS.iter().find(|(name, _)| *name == clip) {
        Some((name, bytes)) => {
            let path = directory.join(format!("{name}.mp4"));
            fs::write(&path, bytes)?;
            path
        }
        None => PathBuf::from(clip),
    };
    MediaInput::open(&path.to_string_lossy())
        .and_then(|mut input| input.video_stream())
        .map_err(|error| io::Error::other(format!("{clip}: {error}")))?;
    Ok(path)
}

#[derive(Debug, Clone, Copy)]
struct StreamFaults {
    drop_after: Option<Duration>,
    stall_after: Option<Duration>,
}

struct Shared {
    clips: Vec<PathBuf>,
    path: String,
    faults: StreamFaults,
    stop: AtomicBool,
    sessions: AtomicU64,
    // Bounded by the open connections, each removing itself when it ends.
    live: Mutex<Vec<(u64, TcpStream)>>,
}

impl Shared {
    fn live(&self) -> std::sync::MutexGuard<'_, Vec<(u64, TcpStream)>> {
        self.live.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Closes every open connection, which ends its session.
    fn close_sessions(&self) {
        for (_, connection) in self.live().drain(..) {
            let _ = connection.shutdown(Shutdown::Both);
        }
    }

    fn forget(&self, id: u64) {
        self.live().retain(|(live, _)| *live != id);
    }
}

struct Accept {
    shared: Arc<Shared>,
    address: SocketAddr,
    refuse: usize,
    restart: Option<(Duration, Duration)>,
}

impl Accept {
    fn run(mut self, mut listener: TcpListener) {
        let mut sessions: Vec<JoinHandle<()>> = Vec::new();
        let mut up_since = Instant::now();
        while !self.stopped() {
            if let Some((after, downtime)) = self.restart
                && up_since.elapsed() >= after
            {
                drop(listener);
                self.shared.close_sessions();
                self.sleep(downtime);
                let Some(rebound) = self.rebind() else {
                    break;
                };
                listener = rebound;
                up_since = Instant::now();
                continue;
            }
            match listener.accept() {
                Ok((connection, _)) if self.refuse > 0 => {
                    self.refuse -= 1;
                    drop(connection);
                }
                Ok((connection, _)) => {
                    sessions.retain(|session| !session.is_finished());
                    if let Ok(session) = self.spawn(connection) {
                        sessions.push(session);
                    }
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => thread::sleep(POLL),
                Err(_) => thread::sleep(POLL),
            }
        }
        self.shared.close_sessions();
        for session in sessions {
            let _ = session.join();
        }
    }

    fn spawn(&self, connection: TcpStream) -> io::Result<JoinHandle<()>> {
        // A socket accepted from a nonblocking listener inherits the mode on some platforms.
        connection.set_nonblocking(false)?;
        let id = self.shared.sessions.fetch_add(1, Ordering::Relaxed);
        self.shared.live().push((id, connection.try_clone()?));
        let shared = Arc::clone(&self.shared);
        thread::Builder::new()
            .name(format!("rtsp-session-{id}"))
            .spawn(move || session::serve(id, connection, &shared))
    }

    /// Binds the same address again, retrying until it is free or the server stops.
    fn rebind(&self) -> Option<TcpListener> {
        while !self.stopped() {
            let listener = TcpListener::bind(self.address)
                .and_then(|listener| listener.set_nonblocking(true).map(|()| listener));
            if let Ok(listener) = listener {
                return Some(listener);
            }
            thread::sleep(POLL);
        }
        None
    }

    fn sleep(&self, duration: Duration) {
        let until = Instant::now() + duration;
        while !self.stopped() && Instant::now() < until {
            thread::sleep(POLL);
        }
    }

    fn stopped(&self) -> bool {
        self.shared.stop.load(Ordering::Relaxed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{MediaError, MediaPacket};

    fn serve(clip: &str) -> RtspServer {
        let options = RtspServerOptions {
            clips: vec![clip.to_owned()],
            ..RtspServerOptions::default()
        };
        RtspServer::start("127.0.0.1:0".parse().unwrap(), options).unwrap()
    }

    fn connect(url: &str) -> Result<MediaInput, MediaError> {
        MediaInput::open_with(url, &[("rtsp_transport", "tcp")], None)
    }

    /// Reads `count` packets and returns the time span their presentation timestamps reach.
    fn play(server: &RtspServer, count: usize) -> Duration {
        let mut input = connect(&server.url()).unwrap();
        let mut packet = MediaPacket::new();
        let mut latest = 0;
        for _ in 0..count {
            assert!(input.read(&mut packet).unwrap());
            latest = latest.max(packet.timing().pts.unwrap_or(0));
        }
        input.time_base(0).duration(latest)
    }

    #[test]
    fn streams_h264_past_the_end_of_the_clip() {
        // The clip is 100 frames at 25 per second, so frame 110 comes from the second loop.
        assert!(play(&serve("h264"), 110) > Duration::from_secs(4));
    }

    #[test]
    fn streams_h265() {
        assert!(play(&serve("h265"), 10) > Duration::ZERO);
    }

    #[test]
    fn unknown_path_is_an_error() {
        let server = serve("h264");
        let url = format!("rtsp://{}/abc", server.address());
        let error = connect(&url).err().unwrap();
        assert!(error.message.contains("404"), "{error}");
    }

    #[test]
    fn unknown_clip_is_an_error() {
        let options = RtspServerOptions {
            clips: vec!["abcd.mp4".to_owned()],
            ..RtspServerOptions::default()
        };
        assert!(RtspServer::start("127.0.0.1:0".parse().unwrap(), options).is_err());
    }
}
