//! Telling a stream whose frames arrive out of display order, as B-frames make them.

use std::sync::atomic::{AtomicU8, Ordering};

use super::PacketStream;

/// The order a track's frames arrive in, as far as its packets so far tell.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum FrameOrder {
    /// Too few packets have arrived to tell.
    Unknown,
    /// Each frame shows after the one before it.
    Display,
    /// Some frame shows before one sent ahead of it, so a player showing frames as they arrive
    /// shows them out of order.
    Reordered,
}

/// A `FrameOrder` shared between the thread reading a stream and any thread asking about it.
#[derive(Debug, Default)]
pub(super) struct SharedFrameOrder(AtomicU8);

impl SharedFrameOrder {
    pub(super) fn get(&self) -> FrameOrder {
        match self.0.load(Ordering::Relaxed) {
            1 => FrameOrder::Display,
            2 => FrameOrder::Reordered,
            _ => FrameOrder::Unknown,
        }
    }

    pub(super) fn set(&self, order: FrameOrder) {
        self.0.store(order as u8, Ordering::Relaxed);
    }
}

/// Watches a track's packet timestamps for frames sent ahead of their display time.
///
/// A source's own codec parameters are no answer, since many live sources leave out the field
/// that declares reordering, so this goes by the packets alone. A track is reordered once a
/// packet shows before the one sent ahead of it, and in display order once a keyframe and two
/// packets after it have each shown later than the last. A track found reordered stays so,
/// since a stream can start reordering partway through.
#[derive(Debug, Default)]
pub(super) struct FrameOrderCheck {
    /// The presentation time of the last packet, in `PacketStream::TIME_BASE`.
    previous: Option<i64>,
    /// Whether a keyframe has arrived since the track began.
    keyed: bool,
    /// The packets since the keyframe that each showed later than the one before.
    in_order: u32,
    reordered: bool,
}

impl FrameOrderCheck {
    /// The largest step back a reordered frame takes, one second of `PacketStream::TIME_BASE`.
    /// A larger one is the timeline restarting, as it does when a source reconnects.
    const MAX_REORDER: i64 = PacketStream::TIME_BASE.den as i64;

    /// The packets after a keyframe that must each show later before the track counts as in
    /// display order. One B-frame between references shows on the second.
    const IN_ORDER_PACKETS: u32 = 2;

    /// Starts over, for the packets of a new track.
    pub(super) fn reset(&mut self) {
        *self = Self::default();
    }

    /// Takes the next packet's presentation time `pts` in `PacketStream::TIME_BASE`, before
    /// any clamping, and whether it is a keyframe, and returns the order so far.
    pub(super) fn observe(&mut self, pts: Option<i64>, key: bool) -> FrameOrder {
        // A keyframe counts even untimed, as a connection's first one is until RTCP arrives.
        if key {
            self.keyed = true;
            self.in_order = 0;
        }
        let Some(pts) = pts else {
            return self.order();
        };
        let step_back = self.previous.map_or(0, |previous| previous - pts);
        if step_back > 0 && step_back < Self::MAX_REORDER {
            self.reordered = true;
        } else if !key && self.keyed && self.previous.is_some() && step_back < 0 {
            self.in_order += 1;
        }
        self.previous = Some(pts);
        self.order()
    }

    /// The order the packets so far show.
    pub(super) fn order(&self) -> FrameOrder {
        if self.reordered {
            FrameOrder::Reordered
        } else if self.keyed && self.in_order >= Self::IN_ORDER_PACKETS {
            FrameOrder::Display
        } else {
            FrameOrder::Unknown
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The order after packets each given as presentation time and whether it is a keyframe.
    fn order(packets: &[(i64, bool)]) -> FrameOrder {
        let mut check = FrameOrderCheck::default();
        for (pts, key) in packets {
            check.observe(Some(*pts), *key);
        }
        check.order()
    }

    #[test]
    fn frames_sent_in_display_order_are_told_after_two_past_the_keyframe() {
        assert_eq!(order(&[(0, true), (3600, false)]), FrameOrder::Unknown);
        assert_eq!(
            order(&[(0, true), (3600, false), (7200, false)]),
            FrameOrder::Display
        );
    }

    #[test]
    fn one_frame_sent_ahead_of_its_turn_is_reordering() {
        // I P B P B, decode order, the B showing before the P sent ahead of it.
        let packets = [(0, true), (7200, false), (3600, false)];
        assert_eq!(order(&packets), FrameOrder::Reordered);
    }

    #[test]
    fn a_reordered_track_stays_so_until_reset() {
        let mut check = FrameOrderCheck::default();
        for (pts, key) in [(0, true), (7200, false), (3600, false), (10800, false)] {
            check.observe(Some(pts), key);
        }
        check.observe(Some(14400), false);
        assert_eq!(check.order(), FrameOrder::Reordered);
        check.reset();
        assert_eq!(check.order(), FrameOrder::Unknown);
    }

    #[test]
    fn a_step_back_of_seconds_is_a_restarted_timeline_not_reordering() {
        let packets = [(180_000, true), (183_600, false), (0, true), (3600, false)];
        assert_eq!(order(&packets), FrameOrder::Unknown);
        let packets = [(180_000, true), (0, true), (3600, false), (7200, false)];
        assert_eq!(order(&packets), FrameOrder::Display);
    }

    #[test]
    fn a_negative_presentation_time_counts_unclamped() {
        let packets = [(0, true), (3600, false), (-3600, false)];
        assert_eq!(order(&packets), FrameOrder::Reordered);
    }

    #[test]
    fn packets_with_no_presentation_time_tell_nothing() {
        let mut check = FrameOrderCheck::default();
        check.observe(Some(0), true);
        check.observe(None, false);
        check.observe(None, false);
        assert_eq!(check.order(), FrameOrder::Unknown);
    }
}
