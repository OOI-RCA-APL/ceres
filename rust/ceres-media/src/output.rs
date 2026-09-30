use std::ffi::{CStr, c_char, c_int, c_void};
use std::io;
use std::marker::PhantomData;
use std::ptr::{self, NonNull};

use crate::error::EIO;
use crate::options::{COptions, c_string};
use crate::{MediaError, MediaPacket, TimeBase, ffi};

/// Receives the muxer's output, one flush per call, each at most the output's packet size.
pub type MediaSink = Box<dyn FnMut(&[u8]) -> io::Result<()> + Send>;

/// The codec and time base of one stream, borrowed from the input or transcoder producing it.
#[derive(Clone, Copy)]
pub struct MediaTrack<'a> {
    parameters: NonNull<ffi::AVCodecParameters>,
    time_base: TimeBase,
    _owner: PhantomData<&'a ()>,
}

impl MediaTrack<'_> {
    /// Wraps `parameters`, which the caller keeps alive and unchanged for the track's lifetime.
    pub(crate) unsafe fn new(
        parameters: *const ffi::AVCodecParameters,
        time_base: TimeBase,
    ) -> Self {
        Self {
            parameters: NonNull::new(parameters.cast_mut()).expect("FFmpeg returned parameters"),
            time_base,
            _owner: PhantomData,
        }
    }

    pub fn time_base(&self) -> TimeBase {
        self.time_base
    }
}

struct SinkState {
    sink: MediaSink,
    error: Option<io::Error>,
}

/// An open muxer writing streams copied from a `MediaInput` into a `MediaSink`.
pub struct MediaOutput {
    // `None` once the muxer is closed.
    context: Option<NonNull<ffi::AVFormatContext>>,
    // Boxed so FFmpeg's pointer to it stays put while `self` moves.
    state: Box<SinkState>,
}

impl MediaOutput {
    /// Opens a `format` muxer with FFmpeg `options` and one stream per track, and writes its
    /// header.
    ///
    /// An option FFmpeg does not recognize is an error.
    pub fn open(
        format: &str,
        options: &[(&str, &str)],
        tracks: &[MediaTrack<'_>],
        packet_size: usize,
        sink: MediaSink,
    ) -> Result<Self, MediaError> {
        let format = c_string(format)?;
        let options = COptions::new(options)?;
        let parameters = tracks
            .iter()
            .map(|track| track.parameters.as_ptr().cast_const())
            .collect::<Vec<_>>();
        let nums = tracks
            .iter()
            .map(|track| track.time_base.num)
            .collect::<Vec<_>>();
        let dens = tracks
            .iter()
            .map(|track| track.time_base.den)
            .collect::<Vec<_>>();
        let packet_size = c_int::try_from(packet_size)
            .map_err(|_| MediaError::invalid(format!("packet size {packet_size} is too large")))?;
        let mut state = Box::new(SinkState { sink, error: None });
        let mut context = ptr::null_mut();
        // SAFETY: Every string is NUL-terminated, `state` outlives the muxer in `Self`, and the
        // shim frees everything it allocated on failure.
        let code = unsafe {
            ffi::ceres_output_open(
                format.as_ptr(),
                options.keys(),
                options.values(),
                options.count(),
                parameters.as_ptr(),
                nums.as_ptr(),
                dens.as_ptr(),
                c_int::try_from(tracks.len()).expect("a handful of streams"),
                packet_size,
                write_sink,
                ptr::from_mut::<SinkState>(&mut state).cast::<c_void>(),
                &raw mut context,
            )
        };
        if code < 0 {
            return Err(error(&mut state, code));
        }
        Ok(Self {
            context: Some(NonNull::new(context).expect("FFmpeg returns a muxer on success")),
            state,
        })
    }

    /// Writes `packet`, timed in `time_base`, to output stream `stream`, leaving it blank.
    pub fn write(
        &mut self,
        stream: usize,
        packet: &mut MediaPacket,
        time_base: TimeBase,
    ) -> Result<(), MediaError> {
        let context = self.context()?;
        let stream = c_int::try_from(stream).expect("stream indexes fit an int");
        // SAFETY: Both pointers are live, and the shim rescales and consumes the packet.
        let code = unsafe {
            ffi::ceres_output_write(
                context.as_ptr(),
                stream,
                packet.as_ptr(),
                time_base.num,
                time_base.den,
            )
        };
        self.check(code)
    }

    /// The time base the muxer chose for output stream `stream`.
    pub fn time_base(&self, stream: usize) -> Result<TimeBase, MediaError> {
        let context = self.context()?;
        let stream = c_int::try_from(stream).expect("stream indexes fit an int");
        let (mut num, mut den) = (0, 0);
        // SAFETY: The muxer is live and the caller names one of its streams.
        unsafe {
            ffi::ceres_output_time_base(context.as_ptr(), stream, &raw mut num, &raw mut den);
        }
        Ok(TimeBase { num, den })
    }

    /// Whether `track` has the codec, size, and parameter sets output stream `stream` was opened
    /// with, so its packets can continue the same track.
    pub fn matches(&self, stream: usize, track: &MediaTrack<'_>) -> Result<bool, MediaError> {
        let context = self.context()?;
        let stream = c_int::try_from(stream).expect("stream indexes fit an int");
        // SAFETY: The muxer is live, the caller names one of its streams, and the track borrows
        // parameters that outlive the call.
        let matches = unsafe {
            ffi::ceres_output_matches(context.as_ptr(), stream, track.parameters.as_ptr())
        };
        Ok(matches != 0)
    }

    /// The SDP describing an `rtp` muxer's stream.
    pub fn sdp(&mut self) -> Result<String, MediaError> {
        let context = self.context()?;
        let mut buffer = [0 as c_char; 4096];
        let size = c_int::try_from(buffer.len()).expect("the buffer fits an int");
        // SAFETY: The shim writes a NUL-terminated string of at most `size` bytes.
        let code = unsafe { ffi::ceres_output_sdp(context.as_ptr(), buffer.as_mut_ptr(), size) };
        self.check(code)?;
        // SAFETY: The shim NUL-terminated the buffer on success.
        let sdp = unsafe { CStr::from_ptr(buffer.as_ptr()) };
        Ok(sdp.to_string_lossy().into_owned())
    }

    /// Writes the trailer, flushes, and closes the muxer.
    pub fn finish(mut self) -> Result<(), MediaError> {
        let code = self.close(false);
        self.check(code)
    }

    fn context(&self) -> Result<NonNull<ffi::AVFormatContext>, MediaError> {
        self.context
            .ok_or_else(|| MediaError::invalid("the muxer is closed"))
    }

    fn close(&mut self, abandon: bool) -> c_int {
        let Some(context) = self.context.take() else {
            return 0;
        };
        let mut context = context.as_ptr();
        // SAFETY: The muxer came from `ceres_output_open` and `take` above closes it only once.
        unsafe { ffi::ceres_output_close(&raw mut context, c_int::from(abandon)) }
    }

    fn check(&mut self, code: c_int) -> Result<(), MediaError> {
        if code < 0 {
            Err(error(&mut self.state, code))
        } else {
            Ok(())
        }
    }
}

impl Drop for MediaOutput {
    fn drop(&mut self) {
        self.close(true);
    }
}

// SAFETY: A muxer has no thread affinity, the sink is `Send`, and `&mut self` serializes every
// call.
unsafe impl Send for MediaOutput {}

/// The error for a failed muxer call, the sink's own where the sink caused it.
fn error(state: &mut SinkState, code: c_int) -> MediaError {
    match state.error.take() {
        Some(error) => MediaError::sink(&error),
        None => MediaError::from_code(code),
    }
}

unsafe extern "C" fn write_sink(opaque: *mut c_void, data: *const u8, size: c_int) -> c_int {
    // SAFETY: `opaque` is the `SinkState` boxed in the `MediaOutput` that owns this muxer, and
    // FFmpeg passes `size` readable bytes.
    let (state, data) = unsafe {
        let size = usize::try_from(size).unwrap_or(0);
        let data = if data.is_null() || size == 0 {
            &[][..]
        } else {
            std::slice::from_raw_parts(data, size)
        };
        (&mut *opaque.cast::<SinkState>(), data)
    };
    if state.error.is_some() {
        return EIO;
    }
    match (state.sink)(data) {
        Ok(()) => c_int::try_from(data.len()).expect("FFmpeg passed an int"),
        Err(error) => {
            state.error = Some(error);
            EIO
        }
    }
}
