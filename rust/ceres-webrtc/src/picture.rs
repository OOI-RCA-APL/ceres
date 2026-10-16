//! The frames a browser starts from.

use ceres_media::MediaPacket;

/// A frame a [`Picture`] holds.
pub(crate) trait Frame {
    fn is_key(&self) -> bool;
    /// How many bytes the frame takes.
    fn bytes(&self) -> usize;
}

impl Frame for MediaPacket {
    fn is_key(&self) -> bool {
        MediaPacket::is_key(self)
    }

    fn bytes(&self) -> usize {
        self.data().len()
    }
}

/// The frames since a source's latest keyframe, held for a browser to start from, since a
/// picture can start only at a keyframe.
///
/// Frames before the first keyframe are not held, and a picture outgrowing `limit` bytes is let
/// go, so the browser starts at the next keyframe rather than a source's long group of pictures
/// waiting in memory.
pub(crate) struct Picture<T> {
    frames: Vec<T>,
    bytes: usize,
    limit: usize,
}

impl<T: Frame> Picture<T> {
    pub(crate) fn new(limit: usize) -> Self {
        Self {
            frames: Vec::new(),
            bytes: 0,
            limit,
        }
    }

    pub(crate) fn hold(&mut self, frame: T) {
        if frame.is_key() {
            self.clear();
        } else if self.frames.is_empty() {
            return;
        }
        self.bytes += frame.bytes();
        if self.bytes > self.limit {
            self.clear();
            return;
        }
        self.frames.push(frame);
    }

    pub(crate) fn clear(&mut self) {
        self.frames.clear();
        self.bytes = 0;
    }

    /// The frames held, oldest first, leaving none.
    pub(crate) fn take(&mut self) -> Vec<T> {
        self.bytes = 0;
        std::mem::take(&mut self.frames)
    }
}

#[cfg(test)]
mod tests {
    use super::{Frame, Picture};

    /// A frame of its bytes, a keyframe when `true`.
    impl Frame for (bool, usize) {
        fn is_key(&self) -> bool {
            self.0
        }

        fn bytes(&self) -> usize {
            self.1
        }
    }

    #[test]
    fn frames_before_the_first_keyframe_are_not_held() {
        let mut picture = Picture::new(100);
        picture.hold((false, 10));
        picture.hold((false, 10));
        assert!(picture.take().is_empty());
    }

    #[test]
    fn a_keyframe_starts_the_picture_over() {
        let mut picture = Picture::new(100);
        picture.hold((true, 10));
        picture.hold((false, 10));
        picture.hold((true, 20));
        picture.hold((false, 30));
        assert_eq!(picture.take(), [(true, 20), (false, 30)]);
    }

    #[test]
    fn a_picture_outgrowing_its_limit_waits_for_the_next_keyframe() {
        let mut picture = Picture::new(25);
        picture.hold((true, 10));
        picture.hold((false, 10));
        picture.hold((false, 10));
        picture.hold((false, 1));
        assert!(picture.take().is_empty());
        picture.hold((true, 10));
        assert_eq!(picture.take(), [(true, 10)]);
    }
}
