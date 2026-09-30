//! Media streaming for Ceres over a statically linked FFmpeg, reached through a small C shim.

mod error;
mod ffi;
mod input;
mod options;
mod output;
mod server;

use std::time::Duration;

pub use error::MediaError;
pub use input::{Interrupt, MediaInput, MediaPacket, PacketTiming};
pub use output::{MediaOutput, MediaSink};
pub use server::{RTSP_CLIPS, RtspServer, RtspServerOptions};

/// The version of the FFmpeg release built into this crate.
pub const FFMPEG_VERSION: &str = env!("CERES_FFMPEG_VERSION");

/// The rational unit a stream's timestamps count, seconds per tick.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TimeBase {
    pub num: i32,
    pub den: i32,
}

impl TimeBase {
    /// The wall-clock span of `ticks`, zero for a negative count.
    pub fn duration(self, ticks: i64) -> Duration {
        let ticks = u128::try_from(ticks).unwrap_or(0);
        let nanos = ticks * self.num.unsigned_abs() as u128 * 1_000_000_000
            / u128::from(self.den.unsigned_abs().max(1));
        Duration::from_nanos(u64::try_from(nanos).unwrap_or(u64::MAX))
    }
}

/// The path of a committed media clip, shared by every test module.
#[cfg(test)]
pub(crate) fn fixture(name: &str) -> String {
    format!("{}/clips/{name}", env!("CARGO_MANIFEST_DIR"))
}
