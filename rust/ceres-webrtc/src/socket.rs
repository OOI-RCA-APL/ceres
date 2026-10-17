//! The UDP sockets every session's media goes through.

use std::collections::VecDeque;
use std::io::{self, IoSliceMut};
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::sync::{Mutex, PoisonError};
use std::time::{Duration, Instant};

use quinn_udp::{BATCH_SIZE, RecvMeta, UdpSocketState};
use socket2::{Domain, Socket, Type};
use tokio::io::Interest;
use tokio::net::UdpSocket;

/// The largest datagram str0m sends or expects, with room to spare.
const DATAGRAM_SIZE: usize = 2048;

/// The most batches of `BATCH_SIZE` datagrams one wake reads, since every session shares one
/// task and a flood on the socket would starve its timeouts and source reads.
const MAX_BATCHES_PER_WAKE: usize = 8;

/// The send buffer each socket asks for, room for several sessions' keyframes at once. A smaller
/// one costs only trips through the socket's queue, so the socket takes whatever the system
/// grants.
const SEND_BUFFER_BYTES: usize = 4 * 1024 * 1024;

/// The most bytes a socket holds back while its send buffer is full. A queue this deep means
/// the host's own network cannot keep up, and a datagram past it goes, as the network would
/// drop it.
const QUEUE_BYTES: usize = 4 * 1024 * 1024;

/// The longest a datagram waits for the send buffer before the socket drops its queue and
/// every session skips to its next keyframe, which keeps live video within this plus one
/// keyframe interval of the source.
pub(crate) const QUEUE_LIMIT: Duration = Duration::from_secs(1);

/// The media port's sockets, at most one per address family and at least one.
///
/// A dual-stack socket reports IPv4 destinations as mapped IPv6 addresses, which match no IPv4
/// candidate, so IPv4 gets a socket of its own.
pub(crate) struct MediaSockets {
    pub(crate) v4: Option<MediaSocket>,
    pub(crate) v6: Option<MediaSocket>,
    port: u16,
}

impl MediaSockets {
    /// Binds `port` at `address` the way the HTTP listeners bind it, so the IPv6 wildcard
    /// serves IPv4 too.
    ///
    /// Port 0 binds a free port, which both families share, though another process may take
    /// the IPv6 one between the two binds. Must be called within a Tokio runtime.
    pub(crate) fn bind(address: IpAddr, port: u16) -> io::Result<Self> {
        let (v4, v6) = match address {
            IpAddr::V6(ip) if ip.is_unspecified() => {
                let v4 = MediaSocket::bind(SocketAddr::new(Ipv4Addr::UNSPECIFIED.into(), port))?;
                let v6 = MediaSocket::bind(SocketAddr::new(address, v4.port()))?;
                (Some(v4), Some(v6))
            }
            IpAddr::V4(_) => (
                Some(MediaSocket::bind(SocketAddr::new(address, port))?),
                None,
            ),
            IpAddr::V6(_) => (
                None,
                Some(MediaSocket::bind(SocketAddr::new(address, port))?),
            ),
        };
        let port = v4.as_ref().or(v6.as_ref()).map_or(port, MediaSocket::port);
        Ok(Self { v4, v6, port })
    }

    pub(crate) fn port(&self) -> u16 {
        self.port
    }

    /// The addresses the sockets receive at, a wildcard standing for every local address of
    /// its family.
    pub(crate) fn addresses(&self) -> impl Iterator<Item = IpAddr> {
        [&self.v4, &self.v6]
            .into_iter()
            .flatten()
            .map(MediaSocket::address)
    }

    /// Sends `contents` to `destination` from the local address `source`, `false` when the
    /// socket's queue is full and it drops the datagram.
    pub(crate) fn send(
        &self,
        source: SocketAddr,
        destination: SocketAddr,
        contents: &[u8],
    ) -> bool {
        let socket = if source.is_ipv4() {
            self.v4.as_ref()
        } else {
            self.v6.as_ref()
        };
        socket.is_none_or(|socket| socket.send(source, destination, contents))
    }
}

/// A UDP socket of one address family that reports which local address each datagram
/// arrived at, since a wildcard socket serves every interface of its family.
pub(crate) struct MediaSocket {
    socket: UdpSocket,
    state: UdpSocketState,
    local: SocketAddr,
    /// A mutex rather than a cell, since the event loop's futures hold the socket across
    /// awaits on a task that may move between threads. Only that task locks it.
    queue: Mutex<Queue>,
    /// Until when every send is refused, as by a full send buffer.
    #[cfg(feature = "testing")]
    refusing_until: Mutex<Option<Instant>>,
}

/// The datagrams a socket holds back while its send buffer is full, sent in order once it
/// drains.
#[derive(Default)]
struct Queue {
    datagrams: VecDeque<Datagram>,
    bytes: usize,
    /// Set from the first time the queue went stale until it keeps up for `QUEUE_LIMIT`, so a
    /// path that stays too narrow logs once rather than every second.
    behind: Option<Behind>,
}

struct Datagram {
    source: SocketAddr,
    destination: SocketAddr,
    contents: Vec<u8>,
    queued: Instant,
}

struct Behind {
    skips: u32,
    last: Instant,
}

impl Queue {
    /// Sends `contents` through `try_send`, which reports `false` while the send buffer is
    /// full, holding it back behind the datagrams already queued or while the buffer refuses
    /// it. `false` when the queue is full too and it drops the datagram.
    fn send(
        &mut self,
        source: SocketAddr,
        destination: SocketAddr,
        contents: &[u8],
        now: Instant,
        mut try_send: impl FnMut(SocketAddr, SocketAddr, &[u8]) -> bool,
    ) -> bool {
        if self.datagrams.is_empty() && try_send(source, destination, contents) {
            self.keep_up(now);
            return true;
        }
        if self.bytes + contents.len() > QUEUE_BYTES {
            return false;
        }
        self.bytes += contents.len();
        self.datagrams.push_back(Datagram {
            source,
            destination,
            contents: contents.to_vec(),
            queued: now,
        });
        true
    }

    /// Sends the queued datagrams through `try_send` in order, until it refuses one.
    fn flush(
        &mut self,
        now: Instant,
        mut try_send: impl FnMut(SocketAddr, SocketAddr, &[u8]) -> bool,
    ) {
        while let Some(datagram) = self.datagrams.front() {
            if !try_send(datagram.source, datagram.destination, &datagram.contents) {
                return;
            }
            let sent = self
                .datagrams
                .pop_front()
                .map_or(0, |datagram| datagram.contents.len());
            self.bytes -= sent;
        }
        self.keep_up(now);
    }

    /// Drops every queued datagram once the oldest has waited past `QUEUE_LIMIT`, `true` when
    /// it did, and the sessions must skip to their next keyframe.
    ///
    /// An empty queue ends a stretch behind too, so one that ends with every session closed
    /// warns again when the next one starts.
    fn fall_behind(&mut self, now: Instant) -> bool {
        let Some(oldest) = self.datagrams.front() else {
            self.keep_up(now);
            return false;
        };
        let waited = now.saturating_duration_since(oldest.queued);
        if waited <= QUEUE_LIMIT {
            return false;
        }
        if self.behind.is_none() {
            log::warn!(
                "WebRTC fell {} bytes ({} datagrams, the oldest {} ms) behind the network, so \
                 every session skips to its next keyframe",
                self.bytes,
                self.datagrams.len(),
                waited.as_millis()
            );
        }
        let skips = self.behind.as_ref().map_or(0, |behind| behind.skips);
        self.behind = Some(Behind {
            skips: skips + 1,
            last: now,
        });
        self.datagrams.clear();
        self.bytes = 0;
        true
    }

    /// Ends a stretch behind the network once the queue has kept up for `QUEUE_LIMIT`.
    fn keep_up(&mut self, now: Instant) {
        if let Some(behind) = &self.behind
            && now.saturating_duration_since(behind.last) > QUEUE_LIMIT
        {
            log::info!(
                "WebRTC caught up with the network, after {} skips to a keyframe",
                behind.skips
            );
            self.behind = None;
        }
    }
}

impl MediaSocket {
    fn bind(address: SocketAddr) -> io::Result<Self> {
        let socket = Socket::new(Domain::for_address(address), Type::DGRAM, None)?;
        if address.is_ipv6() {
            socket.set_only_v6(true)?;
        }
        socket.set_nonblocking(true)?;
        Self::grow_send_buffer(&socket, address);
        socket.bind(&address.into())?;
        let socket = UdpSocket::from_std(socket.into())?;
        let state = UdpSocketState::new((&socket).into())?;
        let local = socket.local_addr()?;
        Ok(Self {
            socket,
            state,
            local,
            queue: Mutex::default(),
            #[cfg(feature = "testing")]
            refusing_until: Mutex::default(),
        })
    }

    /// Refuses every send until `until`, as a send buffer the network never drains does.
    #[cfg(feature = "testing")]
    pub(crate) fn refuse_until(&self, until: Instant) {
        *self
            .refusing_until
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = Some(until);
    }

    /// Asks for `SEND_BUFFER_BYTES` of send buffer. Linux caps the request at
    /// `net.core.wmem_max` without failing, which the queue makes up for.
    fn grow_send_buffer(socket: &Socket, address: SocketAddr) {
        if let Err(error) = socket.set_send_buffer_size(SEND_BUFFER_BYTES) {
            log::debug!("Growing the WebRTC send buffer on {address} failed: {error}");
        }
    }

    fn port(&self) -> u16 {
        self.local.port()
    }

    /// The address this socket is bound to, a wildcard when it serves its whole family.
    pub(crate) fn address(&self) -> IpAddr {
        self.local.ip()
    }

    pub(crate) async fn readable(&self) -> io::Result<()> {
        self.socket.readable().await
    }

    /// Buffers sized for this socket's reads.
    pub(crate) fn buffers(&self) -> ReceiveBuffers {
        // Receive offload coalesces several datagrams into one buffer.
        let size = DATAGRAM_SIZE * self.state.gro_segments();
        ReceiveBuffers(std::array::from_fn(|_| vec![0; size]))
    }

    /// Reads the datagrams waiting, up to `MAX_BATCHES_PER_WAKE` batches, passing each to
    /// `receive` with its source and the local address it arrived at.
    pub(crate) fn receive(
        &self,
        buffers: &mut ReceiveBuffers,
        mut receive: impl FnMut(SocketAddr, SocketAddr, &[u8]),
    ) {
        // The socket stays readable past the cap, so the event loop returns for the rest.
        for _ in 0..MAX_BATCHES_PER_WAKE {
            let mut slices = buffers.0.each_mut().map(|buffer| IoSliceMut::new(buffer));
            let mut metas = [RecvMeta::default(); BATCH_SIZE];
            let read = || {
                self.state
                    .recv((&self.socket).into(), &mut slices, &mut metas)
            };
            let count = match self.socket.try_io(Interest::READABLE, read) {
                Ok(count) => count,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => return,
                Err(error) => {
                    log::warn!(
                        "Reading the WebRTC socket on {} failed: {error}",
                        self.local
                    );
                    return;
                }
            };
            for (meta, slice) in metas.iter().zip(&slices).take(count) {
                let ip = meta.dst_ip.unwrap_or(self.local.ip());
                let destination = SocketAddr::new(ip, self.local.port());
                for datagram in slice[..meta.len].chunks(meta.stride.max(1)) {
                    receive(meta.addr, destination, datagram);
                }
            }
        }
    }

    /// Sends `contents`, holding it back behind the datagrams already queued or while the send
    /// buffer is full. `false` when the queue is full too and the socket drops it.
    fn send(&self, source: SocketAddr, destination: SocketAddr, contents: &[u8]) -> bool {
        self.queue
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .send(
                source,
                destination,
                contents,
                Instant::now(),
                |source, destination, contents| self.try_send(source, destination, contents),
            )
    }

    /// Drops the queue once its oldest datagram waited past `QUEUE_LIMIT`, `true` when the
    /// sessions must skip to their next keyframe.
    pub(crate) fn fall_behind(&self, now: Instant) -> bool {
        self.queue
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .fall_behind(now)
    }

    /// Whether the socket holds datagrams back, which it sends once it turns writable.
    pub(crate) fn is_queueing(&self) -> bool {
        !self
            .queue
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .datagrams
            .is_empty()
    }

    pub(crate) async fn writable(&self) -> io::Result<()> {
        self.socket.writable().await
    }

    /// Sends the queued datagrams in order, until the send buffer fills again.
    pub(crate) fn flush(&self) {
        self.queue
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .flush(Instant::now(), |source, destination, contents| {
                self.try_send(source, destination, contents)
            });
    }

    /// Sends one datagram now, `false` when the send buffer is full.
    fn try_send(&self, source: SocketAddr, destination: SocketAddr, contents: &[u8]) -> bool {
        #[cfg(feature = "testing")]
        if self
            .refusing_until
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .is_some_and(|until| Instant::now() < until)
        {
            return false;
        }
        let transmit = quinn_udp::Transmit {
            destination,
            ecn: None,
            contents,
            segment_size: None,
            src_ip: Some(source.ip()),
        };
        let write = || self.state.try_send((&self.socket).into(), &transmit);
        match self.socket.try_io(Interest::WRITABLE, write) {
            Ok(()) => true,
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => false,
            // Every datagram to a peer that has gone fails alike, so a warning would flood.
            Err(error) => {
                log::debug!("Sending WebRTC media to {destination} failed: {error}");
                true
            }
        }
    }
}

/// The buffers one socket's reads land in, allocated once.
pub(crate) struct ReceiveBuffers([Vec<u8>; BATCH_SIZE]);

#[cfg(test)]
mod tests {
    use std::net::Ipv6Addr;

    use super::*;

    fn bound(address: IpAddr) -> Vec<IpAddr> {
        MediaSockets::bind(address, 0)
            .unwrap()
            .addresses()
            .collect()
    }

    #[tokio::test]
    async fn a_specific_address_binds_one_socket_of_its_family() {
        let v4 = Ipv4Addr::LOCALHOST.into();
        let v6 = Ipv6Addr::LOCALHOST.into();
        assert_eq!(bound(v4), [v4]);
        assert_eq!(bound(v6), [v6]);
    }

    #[tokio::test]
    async fn the_ipv6_wildcard_binds_both_families_on_one_port() {
        let sockets = MediaSockets::bind(Ipv6Addr::UNSPECIFIED.into(), 0).unwrap();
        assert_eq!(
            sockets.addresses().collect::<Vec<_>>(),
            [
                IpAddr::from(Ipv4Addr::UNSPECIFIED),
                Ipv6Addr::UNSPECIFIED.into()
            ]
        );
        let ports = [&sockets.v4, &sockets.v6].map(|socket| socket.as_ref().unwrap().port());
        assert_eq!(ports, [sockets.port(); 2]);
    }

    #[tokio::test]
    async fn a_socket_sends_from_a_buffer_larger_than_the_default() {
        let address = SocketAddr::new(Ipv4Addr::LOCALHOST.into(), 0);
        let plain = std::net::UdpSocket::bind(address).unwrap();
        let plain = socket2::SockRef::from(&plain).send_buffer_size().unwrap();
        let media = MediaSocket::bind(address).unwrap();
        let grown = socket2::SockRef::from(&media.socket)
            .send_buffer_size()
            .unwrap();
        assert!(
            grown > plain,
            "{grown} bytes is no more than the default {plain}"
        );
    }

    /// A send buffer with room for `room` datagrams, which keeps what it takes in `sent`.
    ///
    /// No real socket stands in, since no test can fill one: Linux frees a datagram sent over
    /// loopback from the send buffer as it sends it, and macOS never refuses a UDP send.
    struct Buffer {
        room: usize,
        sent: Vec<u8>,
    }

    impl Buffer {
        fn try_send(&mut self, _: SocketAddr, _: SocketAddr, contents: &[u8]) -> bool {
            if self.room == 0 {
                return false;
            }
            self.room -= 1;
            self.sent.push(contents[0]);
            true
        }
    }

    fn address() -> SocketAddr {
        SocketAddr::new(Ipv4Addr::LOCALHOST.into(), 8189)
    }

    fn refuse(_: SocketAddr, _: SocketAddr, _: &[u8]) -> bool {
        false
    }

    #[test]
    fn a_burst_past_a_full_send_buffer_waits_and_leaves_in_order() {
        let now = Instant::now();
        let mut queue = Queue::default();
        let mut buffer = Buffer {
            room: 3,
            sent: Vec::new(),
        };
        for index in 0..10 {
            let sent = queue.send(
                address(),
                address(),
                &[index; 1200],
                now,
                |source, to, contents| buffer.try_send(source, to, contents),
            );
            assert!(sent);
        }
        assert_eq!(buffer.sent, [0, 1, 2]);
        assert_eq!(queue.bytes, 7 * 1200);

        buffer.room = 4;
        queue.flush(now, |source, to, contents| {
            buffer.try_send(source, to, contents)
        });
        assert_eq!(buffer.sent, [0, 1, 2, 3, 4, 5, 6]);

        // A datagram sent while others wait goes behind them, even with room for it.
        buffer.room = 10;
        assert!(queue.send(
            address(),
            address(),
            &[10; 1200],
            now,
            |source, to, contents| buffer.try_send(source, to, contents)
        ));
        assert_eq!(buffer.sent, [0, 1, 2, 3, 4, 5, 6]);
        queue.flush(now, |source, to, contents| {
            buffer.try_send(source, to, contents)
        });
        assert_eq!(buffer.sent, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
        assert_eq!(queue.bytes, 0);
    }

    #[test]
    fn a_full_queue_drops_the_datagram() {
        let now = Instant::now();
        let mut queue = Queue::default();
        let contents = vec![0; QUEUE_BYTES / 2];
        assert!(queue.send(address(), address(), &contents, now, refuse));
        assert!(queue.send(address(), address(), &contents, now, refuse));
        assert!(!queue.send(address(), address(), &[0], now, refuse));
        assert_eq!(queue.datagrams.len(), 2);
    }

    #[test]
    fn a_queue_waiting_past_its_limit_lets_go_of_everything_in_it() {
        let start = Instant::now();
        let mut queue = Queue::default();
        assert!(!queue.fall_behind(start + QUEUE_LIMIT * 5));
        assert!(queue.send(address(), address(), &[0; 1200], start, refuse));
        assert!(queue.send(
            address(),
            address(),
            &[1; 1200],
            start + QUEUE_LIMIT / 2,
            refuse
        ));

        let limit = start + QUEUE_LIMIT;
        assert!(!queue.fall_behind(limit - Duration::from_millis(1)));
        assert!(!queue.fall_behind(limit));
        assert!(queue.fall_behind(limit + Duration::from_millis(1)));
        assert!(queue.datagrams.is_empty());
        assert_eq!(queue.bytes, 0);

        // What arrives after starts its own wait, so it is not stale at once.
        let later = limit + Duration::from_millis(2);
        assert!(queue.send(address(), address(), &[2; 1200], later, refuse));
        assert!(!queue.fall_behind(later + QUEUE_LIMIT / 2));
        assert_eq!(queue.datagrams.len(), 1);
    }

    #[test]
    fn a_queue_that_keeps_up_for_its_limit_is_no_longer_behind() {
        let start = Instant::now();
        let mut queue = Queue::default();
        let mut buffer = Buffer {
            room: 0,
            sent: Vec::new(),
        };
        assert!(queue.send(address(), address(), &[0; 1200], start, refuse));
        let skipped = start + QUEUE_LIMIT * 2;
        assert!(queue.fall_behind(skipped));

        buffer.room = 10;
        for (after, behind) in [(QUEUE_LIMIT / 2, true), (QUEUE_LIMIT * 2, false)] {
            let sent = queue.send(
                address(),
                address(),
                &[1; 1200],
                skipped + after,
                |source, to, contents| buffer.try_send(source, to, contents),
            );
            assert!(sent);
            assert_eq!(queue.behind.is_some(), behind);
        }
    }

    #[test]
    fn a_queue_left_empty_for_its_limit_is_no_longer_behind() {
        let start = Instant::now();
        let mut queue = Queue::default();
        assert!(queue.send(address(), address(), &[0; 1200], start, refuse));
        let skipped = start + QUEUE_LIMIT * 2;
        assert!(queue.fall_behind(skipped));

        assert!(!queue.fall_behind(skipped + QUEUE_LIMIT / 2));
        assert!(queue.behind.is_some());
        assert!(!queue.fall_behind(skipped + QUEUE_LIMIT * 2));
        assert!(queue.behind.is_none());
    }
}
