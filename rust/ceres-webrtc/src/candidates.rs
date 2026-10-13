//! The addresses a browser is told to reach the media port at.

use std::net::{IpAddr, SocketAddr};

use str0m::Candidate;

/// Returns the candidates for the media port, one host candidate per local address plus one
/// per configured host that is not local.
///
/// A configured host that is not a local address, such as the public address of a host
/// behind NAT, is offered as server reflexive, since datagrams sent to it arrive at a local
/// address and str0m answers only at a host candidate's address. IPv6 addresses are offered
/// only when `v6` says the port has an IPv6 socket to arrive at.
pub(crate) fn candidates(
    port: u16,
    local: &[IpAddr],
    hosts: &[IpAddr],
    v6: bool,
) -> Vec<Candidate> {
    let reachable = |ip: &&IpAddr| ip.is_ipv4() || v6;
    let mut offered: Vec<Candidate> = local
        .iter()
        .filter(reachable)
        .filter(|ip| !link_local(**ip))
        .filter_map(|ip| Candidate::host(SocketAddr::new(*ip, port), "udp").ok())
        .collect();
    for host in hosts
        .iter()
        .filter(reachable)
        .filter(|host| !local.contains(host))
    {
        let base = offered
            .iter()
            .map(Candidate::addr)
            .find(|base| base.is_ipv4() == host.is_ipv4() && !base.ip().is_loopback());
        let Some(base) = base else {
            log::warn!("WebRTC host {host} has no local address of its family to arrive at");
            continue;
        };
        let address = SocketAddr::new(*host, port);
        if let Ok(reflexive) = Candidate::server_reflexive(address, base, "udp") {
            offered.push(reflexive);
        }
    }

    offered
}

/// Returns the addresses of every interface that is up, which the caller reads again for each
/// session so an interface added later, such as a VPN, is offered too.
pub(crate) fn local_addresses() -> Vec<IpAddr> {
    match if_addrs::get_if_addrs() {
        Ok(interfaces) => interfaces
            .into_iter()
            .map(|interface| interface.ip())
            .collect(),
        Err(error) => {
            log::warn!("Listing the network interfaces for WebRTC failed: {error}");
            Vec::new()
        }
    }
}

/// Whether `ip` is link-local, which str0m refuses for IPv4 and a browser cannot reach for
/// IPv6 without a scope the candidate does not carry.
fn link_local(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => ip.is_link_local(),
        IpAddr::V6(ip) => ip.is_unicast_link_local(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn offered(local: &[&str], hosts: &[&str]) -> Vec<String> {
        offered_over(true, local, hosts)
    }

    fn offered_over(v6: bool, local: &[&str], hosts: &[&str]) -> Vec<String> {
        let parse = |ips: &[&str]| ips.iter().map(|ip| ip.parse().unwrap()).collect::<Vec<_>>();
        candidates(8189, &parse(local), &parse(hosts), v6)
            .iter()
            .map(|candidate| format!("{:?} {}", candidate.kind(), candidate.addr()))
            .collect()
    }

    #[test]
    fn without_an_ipv6_socket_only_ipv4_is_offered() {
        assert_eq!(
            offered_over(
                false,
                &["10.0.0.2", "fd00::2"],
                &["203.0.113.5", "2001:db8::5"]
            ),
            ["Host 10.0.0.2:8189", "ServerReflexive 203.0.113.5:8189"]
        );
    }

    #[test]
    fn every_local_address_but_link_local_is_a_host() {
        assert_eq!(
            offered(
                &[
                    "127.0.0.1",
                    "10.0.0.2",
                    "169.254.0.1",
                    "::1",
                    "fe80::1",
                    "fd00::2"
                ],
                &[]
            ),
            [
                "Host 127.0.0.1:8189",
                "Host 10.0.0.2:8189",
                "Host [::1]:8189",
                "Host [fd00::2]:8189"
            ]
        );
    }

    #[test]
    fn a_local_host_is_not_offered_twice() {
        assert_eq!(
            offered(&["10.0.0.2"], &["10.0.0.2"]),
            ["Host 10.0.0.2:8189"]
        );
    }

    #[test]
    fn a_remote_host_is_reflexive_over_a_routable_local_address_of_its_family() {
        assert_eq!(
            offered(
                &["127.0.0.1", "10.0.0.2", "fd00::2"],
                &["203.0.113.5", "2001:db8::5"]
            ),
            [
                "Host 127.0.0.1:8189",
                "Host 10.0.0.2:8189",
                "Host [fd00::2]:8189",
                "ServerReflexive 203.0.113.5:8189",
                "ServerReflexive [2001:db8::5]:8189",
            ]
        );
        assert_eq!(
            offered(&["10.0.0.2"], &["2001:db8::5"]),
            ["Host 10.0.0.2:8189"]
        );
    }
}
