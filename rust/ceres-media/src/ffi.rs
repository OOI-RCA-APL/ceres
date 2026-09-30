//! Declarations of the functions in `shim.c`, the crate's whole FFmpeg surface.

use std::ffi::{c_char, c_int, c_void};
use std::marker::{PhantomData, PhantomPinned};

/// An FFmpeg struct only ever handled through a pointer.
macro_rules! opaque {
    ($($name:ident),*) => {$(
        #[repr(C)]
        pub struct $name {
            _data: [u8; 0],
            _marker: PhantomData<(*mut u8, PhantomPinned)>,
        }
    )*};
}

opaque!(AVFormatContext, AVPacket);

/// FFmpeg's `AV_NOPTS_VALUE`, a fixed constant in its public ABI.
pub const NOPTS: i64 = i64::MIN;

/// FFmpeg's `interrupt_callback`, returning nonzero to abort a blocking call.
pub type InterruptCallback = unsafe extern "C" fn(opaque: *mut c_void) -> c_int;

/// An `AVIOContext` write callback, returning the bytes taken or a negative error.
pub type WriteCallback =
    unsafe extern "C" fn(opaque: *mut c_void, data: *const u8, size: c_int) -> c_int;

unsafe extern "C" {
    pub fn ceres_input_open(
        url: *const c_char,
        keys: *const *const c_char,
        values: *const *const c_char,
        count: c_int,
        interrupt: Option<InterruptCallback>,
        opaque: *mut c_void,
        input: *mut *mut AVFormatContext,
    ) -> c_int;
    pub fn ceres_input_close(input: *mut *mut AVFormatContext);
    pub fn ceres_input_read(input: *mut AVFormatContext, packet: *mut AVPacket) -> c_int;
    pub fn ceres_input_video_stream(input: *mut AVFormatContext) -> c_int;
    pub fn ceres_input_time_base(
        input: *const AVFormatContext,
        stream: c_int,
        num: *mut c_int,
        den: *mut c_int,
    );
    pub fn ceres_packet_alloc() -> *mut AVPacket;
    pub fn ceres_packet_free(packet: *mut *mut AVPacket);
    pub fn ceres_packet_unref(packet: *mut AVPacket);
    pub fn ceres_packet_stream(packet: *const AVPacket) -> c_int;
    pub fn ceres_packet_timing(
        packet: *const AVPacket,
        pts: *mut i64,
        dts: *mut i64,
        duration: *mut i64,
    );
    pub fn ceres_packet_set_timing(packet: *mut AVPacket, pts: i64, dts: i64);
    pub fn ceres_packet_is_key(packet: *const AVPacket) -> c_int;
    pub fn ceres_output_open(
        format: *const c_char,
        keys: *const *const c_char,
        values: *const *const c_char,
        count: c_int,
        input: *const AVFormatContext,
        streams: *const c_int,
        stream_count: c_int,
        packet_size: c_int,
        write: WriteCallback,
        opaque: *mut c_void,
        output: *mut *mut AVFormatContext,
    ) -> c_int;
    pub fn ceres_output_write(
        output: *mut AVFormatContext,
        stream: c_int,
        packet: *mut AVPacket,
        num: c_int,
        den: c_int,
    ) -> c_int;
    pub fn ceres_output_close(output: *mut *mut AVFormatContext, abandon: c_int) -> c_int;
    pub fn ceres_output_sdp(
        output: *mut AVFormatContext,
        buffer: *mut c_char,
        size: c_int,
    ) -> c_int;
    pub fn ceres_error_describe(error: c_int, buffer: *mut c_char, size: usize);
}
