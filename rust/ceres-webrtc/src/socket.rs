//! The UDP sockets every session's media goes through.

use std::io::{self, IoSliceMut};
use std::net::{Ipv4Addr, Ipv6Addr, SocketAddr};

use quinn_udp::{BATCH_SIZE, RecvMeta, UdpSocketState};
use socket2::{Domain, Socket, Type};
use tokio::io::Interest;
use tokio::net::UdpSocket;

/// The largest datagram str0m sends or expects, with room to spare.
const DATAGRAM_SIZE: usize = 2048;

/// The media port's sockets, one per address family.
///
/// A dual-stack socket reports IPv4 destinations as mapped IPv6 addresses, which match no IPv4
/// candidate, so IPv4 gets a socket of its own.
pub(crate) struct MediaSockets {
    pub(crate) v4: MediaSocket,
    pub(crate) v6: Option<MediaSocket>,
}

impl MediaSockets {
    /// Binds `port` on every interface, IPv6 too where the host has it.
    ///
    /// Port 0 binds a free port, which both families share. Must be called within a Tokio
    /// runtime.
    pub(crate) fn bind(port: u16) -> io::Result<Self> {
        let v4 = MediaSocket::bind(SocketAddr::new(Ipv4Addr::UNSPECIFIED.into(), port))?;
        let v6 = SocketAddr::new(Ipv6Addr::UNSPECIFIED.into(), v4.port());
        let v6 = MediaSocket::bind(v6)
            .inspect_err(|error| {
                log::warn!("WebRTC serves IPv4 alone, binding {v6} failed: {error}");
            })
            .ok();
        Ok(Self { v4, v6 })
    }

    pub(crate) fn port(&self) -> u16 {
        self.v4.port()
    }

    /// Sends `contents` to `destination` from the local address `source`.
    pub(crate) fn send(&self, source: SocketAddr, destination: SocketAddr, contents: &[u8]) {
        let socket = if source.is_ipv4() {
            Some(&self.v4)
        } else {
            self.v6.as_ref()
        };
        if let Some(socket) = socket {
            socket.send(source, destination, contents);
        }
    }
}

/// A UDP socket of one address family, bound to the wildcard address so it serves every
/// interface, that reports which local address each datagram arrived at.
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

    fn port(&self) -> u16 {
        self.local.port()
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

    /// Reads every datagram waiting, passing each to `receive` with its source and the local
    /// address it arrived at.
    pub(crate) fn receive(
        &self,
        buffers: &mut ReceiveBuffers,
        mut receive: impl FnMut(SocketAddr, SocketAddr, &[u8]),
    ) {
        loop {
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

    /// Sends `contents`, dropping it when the socket's buffer is full, as the network would.
    fn send(&self, source: SocketAddr, destination: SocketAddr, contents: &[u8]) {
        let transmit = quinn_udp::Transmit {
            destination,
            ecn: None,
            contents,
            segment_size: None,
            src_ip: Some(source.ip()),
        };
        let write = || self.state.try_send((&self.socket).into(), &transmit);
        match self.socket.try_io(Interest::WRITABLE, write) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {}
            // Every datagram to a peer that has gone fails alike, so a warning would flood.
            Err(error) => log::debug!("Sending WebRTC media to {destination} failed: {error}"),
        }
    }
}

/// The buffers one socket's reads land in, allocated once.
pub(crate) struct ReceiveBuffers([Vec<u8>; BATCH_SIZE]);
