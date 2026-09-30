//! Declarations of the functions in `shim.c`, the crate's whole FFmpeg surface.

use std::ffi::{c_char, c_int};
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

unsafe extern "C" {
    pub fn ceres_input_open(url: *const c_char, input: *mut *mut AVFormatContext) -> c_int;
    pub fn ceres_input_close(input: *mut *mut AVFormatContext);
    pub fn ceres_input_read(input: *mut AVFormatContext, packet: *mut AVPacket) -> c_int;
    pub fn ceres_packet_alloc() -> *mut AVPacket;
    pub fn ceres_packet_free(packet: *mut *mut AVPacket);
    pub fn ceres_packet_unref(packet: *mut AVPacket);
    pub fn ceres_packet_stream(packet: *const AVPacket) -> c_int;
    pub fn ceres_error_describe(error: c_int, buffer: *mut c_char, size: usize);
}
