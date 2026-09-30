//! FFmpeg's log output, routed to the `log` crate instead of the process's stderr.

use std::ffi::{CStr, c_char, c_int};
use std::sync::Once;

use crate::ffi;

/// Routes FFmpeg's log to `log` at debug level, once per process.
///
/// Every failure also reaches the caller as a `MediaError`, so the log carries only detail.
pub(crate) fn route() {
    static ROUTED: Once = Once::new();
    // SAFETY: `forward` is a plain function that outlives every FFmpeg call.
    ROUTED.call_once(|| unsafe { ffi::ceres_log_route(forward) });
}

unsafe extern "C" fn forward(level: c_int, line: *const c_char) {
    // SAFETY: The shim passes a terminated line that lives for this call.
    let line = unsafe { CStr::from_ptr(line) }.to_string_lossy();
    log::debug!(target: "ffmpeg", "[{level}] {line}");
}
