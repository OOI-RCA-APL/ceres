//! The UDP sockets every session's media goes through.

use std::io::{self, IoSliceMut};
use std::net::{IpAddr, Ipv4Addr, SocketAddr};

use quinn_udp::{BATCH_SIZE, RecvMeta, UdpSocketState};
use socket2::{Domain, Socket, Type};
use tokio::io::Interest;
use tokio::net::UdpSocket;

/// The largest datagram str0m sends or expects, with room to spare.
const DATAGRAM_SIZE: usize = 2048;

/// The most batches of `BATCH_SIZE` datagrams one wake reads, since every session shares one
/// task and a flood on the socket would starve its timeouts and source reads.
const MAX_BATCHES_PER_WAKE: usize = 8;

/// The send buffer each socket asks for, room for several sessions' keyframes at once, since the
/// socket drops a datagram that finds its buffer full. The system default holds about one.
const SEND_BUFFER_BYTES: usize = 4 * 1024 * 1024;

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
    /// socket dropped it for a full send buffer.
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
        })
    }

    /// Asks for `SEND_BUFFER_BYTES` of send buffer, warning when the system grants less.
    ///
    /// Linux caps the request at `net.core.wmem_max` without failing, and reports twice what
    /// it granted, its own bookkeeping included.
    fn grow_send_buffer(socket: &Socket, address: SocketAddr) {
        if let Err(error) = socket.set_send_buffer_size(SEND_BUFFER_BYTES) {
            log::warn!("Growing the WebRTC send buffer on {address} failed: {error}");
            return;
        }
        let granted = socket.send_buffer_size().unwrap_or(0);
        let granted = if cfg!(target_os = "linux") {
            granted / 2
        } else {
            granted
        };
        if granted < SEND_BUFFER_BYTES {
            log::warn!(
                "The WebRTC socket on {address} got a send buffer of {granted} bytes, short of \
                 the {SEND_BUFFER_BYTES} it asked for, so video may lose packets in bursts. On \
                 Linux, raise `net.core.wmem_max` to at least {SEND_BUFFER_BYTES}."
            );
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

    /// Sends `contents`, `false` when the socket's buffer is full and the socket drops it, as the
    /// network would.
    fn send(&self, source: SocketAddr, destination: SocketAddr, contents: &[u8]) -> bool {
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
}
