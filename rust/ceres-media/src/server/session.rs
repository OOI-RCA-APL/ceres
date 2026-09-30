use std::io::{self, BufRead, BufReader, Read, Write};
use std::net::{Shutdown, TcpStream};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, PoisonError};
use std::thread::{self, JoinHandle};

use super::{Shared, stream};

/// The session ID every response carries, one session per connection.
const SESSION: &str = "12345678";

/// The RTSP methods the server answers, advertised by OPTIONS.
const PUBLIC: &str = "OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN, GET_PARAMETER, SET_PARAMETER";

/// Answers RTSP requests on `connection` until the client leaves or the server closes it.
pub(super) fn serve(id: u64, connection: TcpStream, shared: &Arc<Shared>) {
    let clip = &shared.clips[usize::try_from(id).unwrap_or(0) % shared.clips.len()];
    if let Ok(writer) = connection.try_clone() {
        let writer = Arc::new(Mutex::new(writer));
        let mut reader = BufReader::new(connection);
        let _ = Session {
            clip,
            shared,
            writer,
            player: None,
        }
        .run(&mut reader);
    }
    shared.forget(id);
}

struct Request {
    method: String,
    url: String,
    sequence: String,
    transport: Option<String>,
}

struct Session<'a> {
    clip: &'a Path,
    shared: &'a Arc<Shared>,
    writer: Arc<Mutex<TcpStream>>,
    player: Option<Player>,
}

impl Session<'_> {
    fn run(&mut self, reader: &mut BufReader<TcpStream>) -> io::Result<()> {
        while let Some(request) = read_request(reader)? {
            match request.method.as_str() {
                "OPTIONS" => self.respond(&request, "200 OK", &[("Public", PUBLIC)], "")?,
                "DESCRIBE" => self.describe(&request)?,
                "SETUP" => self.setup(&request)?,
                "PLAY" => {
                    self.respond(&request, "200 OK", &[("Session", SESSION)], "")?;
                    if self.player.is_none() {
                        self.player = Some(Player::start(self.clip, self.shared, &self.writer)?);
                    }
                }
                "TEARDOWN" => {
                    self.respond(&request, "200 OK", &[("Session", SESSION)], "")?;
                    break;
                }
                "GET_PARAMETER" | "SET_PARAMETER" => {
                    self.respond(&request, "200 OK", &[("Session", SESSION)], "")?;
                }
                _ => self.respond(&request, "501 Not Implemented", &[], "")?,
            }
        }
        Ok(())
    }

    fn describe(&self, request: &Request) -> io::Result<()> {
        if url_path(&request.url) != self.shared.path {
            return self.respond(request, "404 Not Found", &[], "");
        }
        match stream::describe(self.clip) {
            Ok(sdp) => {
                let base = format!("{}/", request.url.trim_end_matches('/'));
                let headers = [
                    ("Content-Base", base.as_str()),
                    ("Content-Type", "application/sdp"),
                ];
                self.respond(request, "200 OK", &headers, &sdp)
            }
            Err(_) => self.respond(request, "500 Internal Server Error", &[], ""),
        }
    }

    fn setup(&self, request: &Request) -> io::Result<()> {
        // Streaming over UDP is out of scope, and this answer makes a client retry over TCP.
        let transport = request.transport.as_deref().unwrap_or_default();
        if !transport.contains("RTP/AVP/TCP") {
            return self.respond(request, "461 Unsupported Transport", &[], "");
        }
        let headers = [
            ("Transport", "RTP/AVP/TCP;unicast;interleaved=0-1"),
            ("Session", SESSION),
        ];
        self.respond(request, "200 OK", &headers, "")
    }

    fn respond(
        &self,
        request: &Request,
        status: &str,
        headers: &[(&str, &str)],
        body: &str,
    ) -> io::Result<()> {
        let mut response = format!("RTSP/1.0 {status}\r\nCSeq: {}\r\n", request.sequence);
        for (name, value) in headers {
            response.push_str(&format!("{name}: {value}\r\n"));
        }
        if !body.is_empty() {
            response.push_str(&format!("Content-Length: {}\r\n", body.len()));
        }
        response.push_str("\r\n");
        response.push_str(body);
        let mut writer = self.writer.lock().unwrap_or_else(PoisonError::into_inner);
        writer.write_all(response.as_bytes())
    }
}

impl Drop for Session<'_> {
    fn drop(&mut self) {
        // Closing the socket first unblocks a player stuck writing to a client that stopped
        // reading.
        let writer = self.writer.lock().unwrap_or_else(PoisonError::into_inner);
        let _ = writer.shutdown(Shutdown::Both);
        drop(writer);
        self.player.take();
    }
}

/// A clip streaming to the client on its own thread, stopped and joined when dropped.
struct Player {
    stop: Arc<AtomicBool>,
    thread: Option<JoinHandle<()>>,
}

impl Player {
    fn start(
        clip: &Path,
        shared: &Arc<Shared>,
        writer: &Arc<Mutex<TcpStream>>,
    ) -> io::Result<Self> {
        let stop = Arc::new(AtomicBool::new(false));
        let context = stream::PlayContext {
            clip: clip.to_owned(),
            faults: shared.faults,
            stop: Arc::clone(&stop),
            writer: Arc::clone(writer),
        };
        let thread = thread::Builder::new()
            .name("rtsp-player".to_owned())
            .spawn(move || stream::play(&context))?;
        Ok(Self {
            stop,
            thread: Some(thread),
        })
    }
}

impl Drop for Player {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

/// Reads the next request, skipping the interleaved RTCP frames a client sends between them.
///
/// Returns `None` once the client closes the connection.
fn read_request(reader: &mut BufReader<TcpStream>) -> io::Result<Option<Request>> {
    loop {
        let Some(&first) = reader.fill_buf()?.first() else {
            return Ok(None);
        };
        if first != b'$' {
            break;
        }
        let mut header = [0; 4];
        reader.read_exact(&mut header)?;
        let length = u16::from_be_bytes([header[2], header[3]]);
        io::copy(
            &mut reader.by_ref().take(u64::from(length)),
            &mut io::sink(),
        )?;
    }
    let mut line = String::new();
    if reader.read_line(&mut line)? == 0 {
        return Ok(None);
    }
    let mut parts = line.split_whitespace();
    let method = parts.next().unwrap_or_default().to_owned();
    let url = parts.next().unwrap_or_default().to_owned();
    let (mut sequence, mut transport, mut length) = (String::new(), None, 0);
    loop {
        line.clear();
        if reader.read_line(&mut line)? == 0 {
            return Ok(None);
        }
        let line = line.trim_end();
        if line.is_empty() {
            break;
        }
        let Some((name, value)) = line.split_once(':') else {
            continue;
        };
        let value = value.trim();
        match name.trim().to_ascii_lowercase().as_str() {
            "cseq" => value.clone_into(&mut sequence),
            "transport" => transport = Some(value.to_owned()),
            "content-length" => length = value.parse().unwrap_or(0),
            _ => {}
        }
    }
    io::copy(&mut reader.by_ref().take(length), &mut io::sink())?;
    Ok(Some(Request {
        method,
        url,
        sequence,
        transport,
    }))
}

/// The path of an `rtsp://host:port/path` URL, without its surrounding slashes.
fn url_path(url: &str) -> &str {
    let rest = url.strip_prefix("rtsp://").unwrap_or(url);
    let path = rest.split_once('/').map_or("", |(_, path)| path);
    path.trim_matches('/')
}
