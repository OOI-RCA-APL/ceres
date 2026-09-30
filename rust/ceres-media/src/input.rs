use std::ffi::{c_int, c_void};
use std::ptr::{self, NonNull};

use crate::options::{COptions, c_string};
use crate::{MediaError, TimeBase, ffi, logging};

/// A predicate polled while a demuxer blocks, returning `true` to abort the call.
pub type Interrupt = Box<dyn Fn() -> bool + Send>;

/// An open demuxer, reading packets from a file or network URL.
pub struct MediaInput {
    context: NonNull<ffi::AVFormatContext>,
    // Boxed twice so FFmpeg holds a thin pointer that stays put while `self` moves.
    _interrupt: Option<Box<Interrupt>>,
}

impl MediaInput {
    /// Opens `url` and probes its streams.
    pub fn open(url: &str) -> Result<Self, MediaError> {
        Self::open_with(url, &[], None)
    }

    /// Opens `url` with FFmpeg demuxer `options`, polling `interrupt` whenever a call blocks.
    ///
    /// An option FFmpeg does not recognize is an error.
    pub fn open_with(
        url: &str,
        options: &[(&str, &str)],
        interrupt: Option<Interrupt>,
    ) -> Result<Self, MediaError> {
        logging::route();
        let url = c_string(url)?;
        let options = COptions::new(options)?;
        let interrupt = interrupt.map(Box::new);
        let (callback, opaque) = match &interrupt {
            Some(interrupt) => (
                Some(poll_interrupt as ffi::InterruptCallback),
                ptr::from_ref::<Interrupt>(interrupt)
                    .cast_mut()
                    .cast::<c_void>(),
            ),
            None => (None, ptr::null_mut()),
        };
        let mut context = ptr::null_mut();
        // SAFETY: Every string is NUL-terminated, `opaque` outlives the context in `Self`, and
        // the shim frees the context on failure.
        MediaError::check(unsafe {
            ffi::ceres_input_open(
                url.as_ptr(),
                options.keys(),
                options.values(),
                options.count(),
                callback,
                opaque,
                &raw mut context,
            )
        })?;
        let context = NonNull::new(context).expect("FFmpeg returns a context on success");
        Ok(Self {
            context,
            _interrupt: interrupt,
        })
    }

    /// The index of the input's main video stream.
    pub fn video_stream(&mut self) -> Result<usize, MediaError> {
        // SAFETY: The context is live.
        let stream = unsafe { ffi::ceres_input_video_stream(self.context.as_ptr()) };
        MediaError::check(stream).map(|stream| stream as usize)
    }

    /// The time base packets of `stream` are timed in.
    pub fn time_base(&self, stream: usize) -> TimeBase {
        let (mut num, mut den) = (0, 0);
        let stream = c_int::try_from(stream).expect("stream indexes fit an int");
        // SAFETY: The context is live, and the shim reads only the stream's time base.
        unsafe {
            ffi::ceres_input_time_base(self.context.as_ptr(), stream, &raw mut num, &raw mut den);
        }
        TimeBase { num, den }
    }

    /// Reads the next packet into `packet`, returning `false` at the end of the input.
    pub fn read(&mut self, packet: &mut MediaPacket) -> Result<bool, MediaError> {
        packet.clear();
        // SAFETY: Both pointers are live, and `clear` left the packet blank as FFmpeg requires.
        let code = unsafe { ffi::ceres_input_read(self.context.as_ptr(), packet.raw.as_ptr()) };
        MediaError::check(code).map(|read| read == 1)
    }

    pub(crate) fn as_ptr(&self) -> *mut ffi::AVFormatContext {
        self.context.as_ptr()
    }
}

impl Drop for MediaInput {
    fn drop(&mut self) {
        let mut context = self.context.as_ptr();
        // SAFETY: The context came from `ceres_input_open` and is closed only here.
        unsafe { ffi::ceres_input_close(&raw mut context) };
    }
}

// SAFETY: A demuxer has no thread affinity, the interrupt is `Send`, and `&mut self` serializes
// every call.
unsafe impl Send for MediaInput {}

unsafe extern "C" fn poll_interrupt(opaque: *mut c_void) -> c_int {
    // SAFETY: `opaque` is the `Interrupt` boxed in the `MediaInput` that owns this context.
    let interrupt = unsafe { &*opaque.cast::<Interrupt>() };
    c_int::from(interrupt())
}

/// A packet's timing in its stream's time base.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PacketTiming {
    pub pts: Option<i64>,
    pub dts: Option<i64>,
    /// Zero where the demuxer does not know it.
    pub duration: i64,
}

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

    pub fn timing(&self) -> PacketTiming {
        let (mut pts, mut dts, mut duration) = (0, 0, 0);
        // SAFETY: The packet is live, and the shim only reads its timing fields.
        unsafe {
            ffi::ceres_packet_timing(
                self.raw.as_ptr(),
                &raw mut pts,
                &raw mut dts,
                &raw mut duration,
            );
        }
        let set = |value| (value != ffi::NOPTS).then_some(value);
        PacketTiming {
            pts: set(pts),
            dts: set(dts),
            duration: duration.max(0),
        }
    }

    pub fn set_timing(&mut self, timing: PacketTiming) {
        let value = |value: Option<i64>| value.unwrap_or(ffi::NOPTS);
        // SAFETY: The packet is live, and the shim only writes its timing fields.
        unsafe {
            ffi::ceres_packet_set_timing(
                self.raw.as_ptr(),
                value(timing.pts),
                value(timing.dts),
                timing.duration,
            );
        }
    }

    /// Shifts the packet's timestamps by `offset`, leaving unset ones unset.
    pub fn shift(&mut self, offset: i64) {
        let timing = self.timing();
        self.set_timing(PacketTiming {
            pts: timing.pts.map(|pts| pts + offset),
            dts: timing.dts.map(|dts| dts + offset),
            duration: timing.duration,
        });
    }

    pub fn is_key(&self) -> bool {
        // SAFETY: The packet is live, and the shim only reads its flags.
        unsafe { ffi::ceres_packet_is_key(self.raw.as_ptr()) != 0 }
    }

    pub(crate) fn as_ptr(&mut self) -> *mut ffi::AVPacket {
        self.raw.as_ptr()
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
    use crate::fixture;

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

    #[test]
    fn unknown_option_is_an_error() {
        let error = MediaInput::open_with(&fixture("h264.mp4"), &[("abcd", "1")], None);
        assert!(error.is_err_and(|error| error.message.contains("Option not found")));
    }

    #[test]
    fn interrupt_aborts_open() {
        let error = MediaInput::open_with(&fixture("h264.mp4"), &[], Some(Box::new(|| true)));
        assert!(error.is_err_and(|error| error.message.contains("Immediate exit")));
    }
}
