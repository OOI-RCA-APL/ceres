//! How well a session's media reaches its browser, from the reports str0m makes of it.

use std::time::{Duration, Instant};

use str0m::bwe::Bitrate;
use str0m::stats::MediaEgressStats;

/// How often str0m reports a session's delivery.
pub(crate) const REPORT_INTERVAL: Duration = Duration::from_secs(1);

/// A session's delivery so far, each count from the start of the session.
#[derive(Debug)]
pub(crate) struct Delivery {
    started: Instant,
    /// The datagrams the socket dropped for a full send buffer.
    dropped: u64,
    /// The packets the session sent, resends included.
    sent: u64,
    /// The packets the browser reports it never received.
    lost: u64,
    /// The times the browser asked for lost packets again.
    nacks: u64,
    /// The bytes the session had sent at the last report, and when the report came.
    bytes: Option<(u64, Instant)>,
    /// The bandwidth str0m last estimated the path to the browser has.
    estimate: Option<Bitrate>,
}

/// One report's worth of delivery.
#[derive(Debug, PartialEq)]
pub(crate) struct Report {
    /// The rate the session sent at since the last report, `None` for the first.
    pub(crate) rate: Option<Bitrate>,
    pub(crate) sent: u64,
    pub(crate) lost: u64,
    pub(crate) nacks: u64,
}

impl Delivery {
    pub(crate) fn new(started: Instant) -> Self {
        Self {
            started,
            dropped: 0,
            sent: 0,
            lost: 0,
            nacks: 0,
            bytes: None,
            estimate: None,
        }
    }

    /// Counts a datagram the socket dropped, `true` for the session's first.
    pub(crate) fn drop_datagram(&mut self) -> bool {
        self.dropped += 1;
        self.dropped == 1
    }

    pub(crate) fn estimate(&mut self, estimate: Bitrate) {
        self.estimate = Some(estimate);
    }

    /// Takes str0m's latest report, returning what changed since the one before.
    pub(crate) fn report(&mut self, stats: &MediaEgressStats) -> Report {
        let lost = stats
            .remote
            .as_ref()
            .map_or(self.lost, |remote| remote.packets_lost);
        let rate = self.bytes.and_then(|(bytes, at)| {
            let elapsed = stats.timestamp.saturating_duration_since(at).as_secs_f64();
            let sent = stats.bytes.saturating_sub(bytes);
            #[expect(clippy::cast_precision_loss, reason = "a rate needs no exact count")]
            (elapsed > 0.0).then(|| Bitrate::from(sent as f64 * 8.0 / elapsed))
        });
        let report = Report {
            rate,
            sent: stats.packets.saturating_sub(self.sent),
            lost: lost.saturating_sub(self.lost),
            nacks: stats.nacks.saturating_sub(self.nacks),
        };
        self.sent = stats.packets;
        self.lost = lost;
        self.nacks = stats.nacks;
        self.bytes = Some((stats.bytes, stats.timestamp));
        report
    }

    /// One line for the log once the session ends.
    pub(crate) fn summary(&self, now: Instant) -> String {
        let seconds = now.saturating_duration_since(self.started).as_secs();
        let estimate = self
            .estimate
            .map_or_else(|| "none".into(), |estimate| estimate.to_string());
        format!(
            "sent {} packets in {seconds} s, the browser lost {} and asked for {} again, {} \
             never left this host for a full send buffer, last bandwidth estimate {estimate}",
            self.sent, self.lost, self.nacks, self.dropped
        )
    }
}

#[cfg(test)]
mod tests {
    use str0m::media::Mid;
    use str0m::stats::RemoteIngressStats;

    use super::*;

    fn stats(at: Instant, bytes: u64, packets: u64, lost: u64, nacks: u64) -> MediaEgressStats {
        MediaEgressStats {
            mid: Mid::from("0"),
            rid: None,
            bytes,
            packets,
            firs: 0,
            plis: 0,
            nacks,
            rtt: None,
            loss: None,
            timestamp: at,
            remote: Some(RemoteIngressStats {
                jitter: 0,
                maximum_sequence_number: 0.into(),
                packets_lost: lost,
            }),
        }
    }

    #[test]
    fn each_report_counts_what_changed_since_the_last() {
        let start = Instant::now();
        let mut delivery = Delivery::new(start);
        let first = delivery.report(&stats(start, 1000, 10, 0, 0));
        assert_eq!(
            first,
            Report {
                rate: None,
                sent: 10,
                lost: 0,
                nacks: 0
            }
        );
        let second = delivery.report(&stats(start + REPORT_INTERVAL, 126_000, 110, 3, 2));
        assert_eq!(
            second,
            Report {
                rate: Some(Bitrate::mbps(1)),
                sent: 100,
                lost: 3,
                nacks: 2
            }
        );
    }

    #[test]
    fn only_the_first_dropped_datagram_is_news() {
        let mut delivery = Delivery::new(Instant::now());
        assert!(delivery.drop_datagram());
        assert!(!delivery.drop_datagram());
        assert!(delivery.summary(Instant::now()).contains("2 never left"));
    }
}
