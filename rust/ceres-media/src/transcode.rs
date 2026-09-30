use std::ffi::c_int;
use std::ptr::{self, NonNull};

use crate::{MediaError, MediaInput, MediaPacket, MediaTrack, TimeBase, ffi};

/// Decodes a source's video and re-encodes it as H.264 with OpenH264.
///
/// The encoder opens on the first decoded frame and lasts the transcoder's lifetime, so its
/// output stays one track across connections. Each connection opens its own decoder.
pub struct MediaTranscoder {
    raw: NonNull<ffi::CeresTranscoder>,
    time_base: TimeBase,
}

// SAFETY: The transcoder's codecs belong to it alone, and FFmpeg allows moving a codec context
// between threads while nothing else uses it.
unsafe impl Send for MediaTranscoder {}

impl MediaTranscoder {
    /// Opens a transcoder whose packets, in and out, are timed in `time_base`.
    pub fn open(time_base: TimeBase) -> Result<Self, MediaError> {
        let mut raw = ptr::null_mut();
        // SAFETY: The shim sets `raw` only on success.
        let code =
            unsafe { ffi::ceres_transcoder_open(time_base.num, time_base.den, &raw mut raw) };
        MediaError::check(code)?;
        Ok(Self {
            raw: NonNull::new(raw).expect("the shim set the transcoder"),
            time_base,
        })
    }

    pub fn time_base(&self) -> TimeBase {
        self.time_base
    }

    /// Opens a decoder for `input`'s stream `stream`, replacing the previous connection's.
    pub fn connect(&mut self, input: &mut MediaInput, stream: usize) -> Result<(), MediaError> {
        let stream = c_int::try_from(stream).expect("stream indexes fit an int");
        // SAFETY: Both pointers are live and the caller names a stream of the input.
        let code =
            unsafe { ffi::ceres_transcoder_connect(self.raw.as_ptr(), input.as_ptr(), stream) };
        MediaError::check(code).map(drop)
    }

    /// Decodes `packet`, timed in the transcoder's time base, leaving it blank.
    pub fn send(&mut self, packet: &mut MediaPacket) -> Result<(), MediaError> {
        // SAFETY: Both pointers are live, and the shim leaves the packet blank.
        let code = unsafe { ffi::ceres_transcoder_send(self.raw.as_ptr(), packet.as_ptr()) };
        MediaError::check(code).map(drop)
    }

    /// Takes the next encoded packet, `false` when the decoder needs another packet first.
    ///
    /// A frame whose size or format differs from the first fails with FFmpeg's
    /// `AVERROR_INPUT_CHANGED`, since the encoder's output is one track.
    pub fn receive(&mut self, packet: &mut MediaPacket) -> Result<bool, MediaError> {
        packet.clear();
        // SAFETY: Both pointers are live, and `clear` left the packet blank as FFmpeg requires.
        let code = unsafe { ffi::ceres_transcoder_receive(self.raw.as_ptr(), packet.as_ptr()) };
        MediaError::check(code).map(|received| received == 1)
    }

    /// The encoder's codec and time base, `None` until a frame has opened the encoder.
    pub fn track(&self) -> Option<MediaTrack<'_>> {
        // SAFETY: The transcoder is live and owns the parameters for as long as the track borrows
        // it.
        unsafe {
            let parameters = ffi::ceres_transcoder_parameters(self.raw.as_ptr());
            (!parameters.is_null()).then(|| MediaTrack::new(parameters, self.time_base))
        }
    }
}

impl Drop for MediaTranscoder {
    fn drop(&mut self) {
        let mut raw = self.raw.as_ptr();
        // SAFETY: The transcoder is live, and the shim frees it and everything it owns.
        unsafe { ffi::ceres_transcoder_close(&raw mut raw) };
    }
}
