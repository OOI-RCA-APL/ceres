//! Media streaming for Ceres over a statically linked FFmpeg, reached through a small C shim.

mod error;
mod ffi;
mod input;

pub use error::MediaError;
pub use input::{MediaInput, MediaPacket};

/// The version of the FFmpeg release built into this crate.
pub const FFMPEG_VERSION: &str = env!("CERES_FFMPEG_VERSION");
