//! Live video from a ceres media source to browsers over WebRTC.
//!
//! One UDP port serves every session. A browser posts an SDP offer, and the server answers
//! once the source has its first picture, then sends that source's H.264 or H.265 packets as
//! they arrive, without re-encoding them. A browser whose offer cannot receive the source's
//! codec is refused, and plays the source over HTTP instead. So is one whose source sends
//! frames out of display order, unless it asks for the frames nothing references to be dropped.

mod candidates;
mod delivery;
mod parameter_sets;
mod picture;
mod server;
mod session;
mod socket;

pub use ceres_media::LiveSource;

pub use self::server::{
    OPEN_TRACK_TIMEOUT, ReorderedFrames, WebrtcAnswer, WebrtcError, WebrtcServer,
};
