use crate::PacketTiming;

/// Places each connection's packets on one output timeline, so a reconnect continues the
/// track where the previous connection ended.
#[derive(Debug, Default)]
pub(crate) struct Timeline {
    // Past every placed packet's presentation, where the next connection starts.
    end: i64,
    last_dts: Option<i64>,
    // The offset from the current connection's timestamps to the timeline's.
    shift: Option<i64>,
}

impl Timeline {
    /// Starts a new connection, whose first packet lands at the current end.
    pub(crate) fn reconnect(&mut self) {
        self.shift = None;
    }

    /// Places `timing`, already in the output time base, or `None` when the packet carries no
    /// timestamp to place.
    pub(crate) fn place(&mut self, timing: PacketTiming) -> Option<PacketTiming> {
        let source = timing.dts.or(timing.pts)?;
        let shift = *self.shift.get_or_insert(self.end - source);
        // The muxer rejects a decode timestamp that does not increase.
        let dts = match self.last_dts {
            Some(last) if source + shift <= last => last + 1,
            _ => source + shift,
        };
        let pts = timing.pts.map_or(dts, |pts| (pts + shift).max(dts));
        self.last_dts = Some(dts);
        self.end = self.end.max(pts + timing.duration.max(0)).max(dts + 1);
        Some(PacketTiming {
            pts: Some(pts),
            dts: Some(dts),
            duration: timing.duration,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    type Stamp = (Option<i64>, Option<i64>);

    /// Places each connection's `(pts, dts)` stamps, ten ticks long, and returns what landed.
    fn place(connections: &[&[Stamp]]) -> Vec<Option<(i64, i64)>> {
        let mut timeline = Timeline::default();
        let mut placed = Vec::new();
        for connection in connections {
            timeline.reconnect();
            for &(pts, dts) in *connection {
                let timing = timeline.place(PacketTiming {
                    pts,
                    dts,
                    duration: 10,
                });
                placed.push(timing.map(|timing| (timing.pts.unwrap(), timing.dts.unwrap())));
            }
        }
        placed
    }

    #[test]
    fn first_connection_starts_at_zero() {
        let placed = place(&[&[(Some(1000), Some(1000)), (Some(1010), Some(1010))]]);
        assert_eq!(placed, [Some((0, 0)), Some((10, 10))]);
    }

    #[test]
    fn reconnect_continues_after_the_end() {
        let placed = place(&[
            &[(Some(0), Some(0)), (Some(10), Some(10))],
            &[(Some(500), Some(500))],
        ]);
        assert_eq!(placed, [Some((0, 0)), Some((10, 10)), Some((20, 20))]);
    }

    #[test]
    fn reordered_frames_keep_their_offset() {
        let placed = place(&[
            &[(Some(20), Some(0)), (Some(10), Some(10))],
            &[(Some(40), Some(20))],
        ]);
        assert_eq!(placed, [Some((20, 0)), Some((10, 10)), Some((50, 30))]);
    }

    #[test]
    fn repeated_dts_is_bumped() {
        let placed = place(&[&[(Some(0), Some(0)), (Some(0), Some(0))]]);
        assert_eq!(placed, [Some((0, 0)), Some((1, 1))]);
    }

    #[test]
    fn missing_dts_uses_pts() {
        let placed = place(&[&[(Some(5), None)]]);
        assert_eq!(placed, [Some((0, 0))]);
    }

    #[test]
    fn packet_without_timestamps_is_dropped() {
        let placed = place(&[&[(None, None)]]);
        assert_eq!(placed, [None]);
    }
}
