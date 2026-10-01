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

    /// Places `timing`, already in the output time base.
    pub(crate) fn place(&mut self, timing: PacketTiming) -> PacketTiming {
        let placed = match timing.dts.or(timing.pts) {
            Some(source) => {
                let shift = *self.shift.get_or_insert(self.end - source);
                (timing.pts.map(|pts| pts + shift), source + shift)
            }
            // RTP carries no timestamp on a connection's first frame until an RTCP report
            // arrives, and that frame is the keyframe every later one needs, so it is placed
            // where the stream stands and the next timestamp's shift lines up behind it.
            None => match (self.shift, self.last_dts) {
                (Some(_), Some(last)) => (None, last + timing.duration.max(1)),
                _ => (None, self.end),
            },
        };
        let (pts, dts) = placed;
        // The muxer rejects a decode timestamp that does not increase.
        let dts = match self.last_dts {
            Some(last) if dts <= last => last + 1,
            _ => dts,
        };
        let pts = pts.map_or(dts, |pts| pts.max(dts));
        self.last_dts = Some(dts);
        self.end = self.end.max(pts + timing.duration.max(0)).max(dts + 1);
        PacketTiming {
            pts: Some(pts),
            dts: Some(dts),
            duration: timing.duration,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    type Stamp = (Option<i64>, Option<i64>);

    /// Places each connection's `(pts, dts)` stamps, ten ticks long, and returns what landed.
    fn place(connections: &[&[Stamp]]) -> Vec<(i64, i64)> {
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
                placed.push((timing.pts.unwrap(), timing.dts.unwrap()));
            }
        }
        placed
    }

    #[test]
    fn first_connection_starts_at_zero() {
        let placed = place(&[&[(Some(1000), Some(1000)), (Some(1010), Some(1010))]]);
        assert_eq!(placed, [(0, 0), (10, 10)]);
    }

    #[test]
    fn reconnect_continues_after_the_end() {
        let placed = place(&[
            &[(Some(0), Some(0)), (Some(10), Some(10))],
            &[(Some(500), Some(500))],
        ]);
        assert_eq!(placed, [(0, 0), (10, 10), (20, 20)]);
    }

    #[test]
    fn reordered_frames_keep_their_offset() {
        let placed = place(&[
            &[(Some(20), Some(0)), (Some(10), Some(10))],
            &[(Some(40), Some(20))],
        ]);
        assert_eq!(placed, [(20, 0), (10, 10), (50, 30)]);
    }

    #[test]
    fn repeated_dts_is_bumped() {
        let placed = place(&[&[(Some(0), Some(0)), (Some(0), Some(0))]]);
        assert_eq!(placed, [(0, 0), (1, 1)]);
    }

    #[test]
    fn missing_dts_uses_pts() {
        let placed = place(&[&[(Some(5), None)]]);
        assert_eq!(placed, [(0, 0)]);
    }

    #[test]
    fn untimed_first_packet_leads_each_connection() {
        let placed = place(&[
            &[(None, None), (Some(1000), Some(1000))],
            &[(None, None), (Some(500), Some(500))],
        ]);
        assert_eq!(placed, [(0, 0), (10, 10), (20, 20), (30, 30)]);
    }

    #[test]
    fn untimed_packet_follows_the_previous_one() {
        let placed = place(&[&[(Some(0), Some(0)), (None, None), (Some(20), Some(20))]]);
        assert_eq!(placed, [(0, 0), (10, 10), (20, 20)]);
    }
}
