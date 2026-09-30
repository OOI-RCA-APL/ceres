use std::ffi::CString;
use std::ptr::{self, NonNull};

use crate::{MediaError, ffi};

/// FFmpeg's `AVERROR(EINVAL)`, the same on every platform FFmpeg supports.
const EINVAL: i32 = -22;

/// An open demuxer, reading packets from a file or network URL.
pub struct MediaInput {
    context: NonNull<ffi::AVFormatContext>,
}

impl MediaInput {
    /// Opens `url` and probes its streams.
    pub fn open(url: &str) -> Result<Self, MediaError> {
        let url = CString::new(url).map_err(|_| MediaError {
            code: EINVAL,
            message: "URL contains a NUL byte".to_owned(),
        })?;
        let mut context = ptr::null_mut();
        // SAFETY: `url` is NUL-terminated, and the shim frees the context on failure.
        MediaError::check(unsafe { ffi::ceres_input_open(url.as_ptr(), &raw mut context) })?;
        let context = NonNull::new(context).expect("FFmpeg returns a context on success");
        Ok(Self { context })
    }

    /// Reads the next packet into `packet`, returning `false` at the end of the input.
    pub fn read(&mut self, packet: &mut MediaPacket) -> Result<bool, MediaError> {
        packet.clear();
        // SAFETY: Both pointers are live, and `clear` left the packet blank as FFmpeg requires.
        let code = unsafe { ffi::ceres_input_read(self.context.as_ptr(), packet.raw.as_ptr()) };
        MediaError::check(code).map(|read| read == 1)
    }
}

impl Drop for MediaInput {
    fn drop(&mut self) {
        let mut context = self.context.as_ptr();
        // SAFETY: The context came from `ceres_input_open` and is closed only here.
        unsafe { ffi::ceres_input_close(&raw mut context) };
    }
}

// SAFETY: A demuxer has no thread affinity, and `&mut self` serializes every call.
unsafe impl Send for MediaInput {}

/// A packet buffer, reused across reads.
pub struct MediaPacket {
    raw: NonNull<ffi::AVPacket>,
}

impl MediaPacket {
    pub fn new() -> Self {
        // SAFETY: Allocation has no preconditions, and a null result is an allocation failure.
        let raw = unsafe { ffi::ceres_packet_alloc() };
        Self {
            raw: NonNull::new(raw).expect("allocate an FFmpeg packet"),
        }
    }

    /// The index of the stream this packet belongs to.
    pub fn stream(&self) -> usize {
        // SAFETY: The packet is live, and FFmpeg sets a non-negative index on every read.
        let stream = unsafe { ffi::ceres_packet_stream(self.raw.as_ptr()) };
        usize::try_from(stream).expect("stream indexes are non-negative")
    }

    fn clear(&mut self) {
        // SAFETY: The packet is live, and unreferencing a blank packet is a no-op.
        unsafe { ffi::ceres_packet_unref(self.raw.as_ptr()) };
    }
}

impl Default for MediaPacket {
    fn default() -> Self {
        Self::new()
    }
}

impl Drop for MediaPacket {
    fn drop(&mut self) {
        let mut raw = self.raw.as_ptr();
        // SAFETY: The packet came from `ceres_packet_alloc` and is freed only here.
        unsafe { ffi::ceres_packet_free(&raw mut raw) };
    }
}

// SAFETY: A packet has no thread affinity, and `&mut self` serializes every mutation.
unsafe impl Send for MediaPacket {}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(name: &str) -> String {
        format!(
            "{}/../../tests/fixtures/rtsp/{name}",
            env!("CARGO_MANIFEST_DIR")
        )
    }

    fn packet_count(url: &str) -> Result<usize, MediaError> {
        let mut input = MediaInput::open(url)?;
        let mut packet = MediaPacket::new();
        let mut count = 0;
        while input.read(&mut packet)? {
            assert_eq!(packet.stream(), 0);
            count += 1;
        }
        Ok(count)
    }

    #[test]
    fn reads_every_h264_packet() {
        assert_eq!(packet_count(&fixture("h264.mp4")), Ok(100));
    }

    #[test]
    fn reads_every_h265_packet() {
        assert_eq!(packet_count(&fixture("h265.mp4")), Ok(100));
    }

    #[test]
    fn missing_file_is_an_error() {
        let error = packet_count(&fixture("missing.mp4")).unwrap_err();
        assert!(error.message.contains("No such file"), "{error}");
    }
}
