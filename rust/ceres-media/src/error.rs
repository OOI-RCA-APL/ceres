use std::ffi::{CStr, c_char, c_int};
use std::fmt;

use crate::ffi;

/// A failed FFmpeg call, with FFmpeg's error code and its description.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MediaError {
    pub code: i32,
    pub message: String,
}

impl MediaError {
    pub(crate) fn from_code(code: c_int) -> Self {
        let mut buffer = [0 as c_char; 256];
        // SAFETY: The shim writes a NUL-terminated string of at most `buffer.len()` bytes.
        let message = unsafe {
            ffi::ceres_error_describe(code, buffer.as_mut_ptr(), buffer.len());
            CStr::from_ptr(buffer.as_ptr())
        };
        Self {
            code,
            message: message.to_string_lossy().into_owned(),
        }
    }

    /// Returns `Ok` with a non-negative return code and the error for a negative one.
    pub(crate) fn check(code: c_int) -> Result<c_int, Self> {
        if code < 0 {
            Err(Self::from_code(code))
        } else {
            Ok(code)
        }
    }
}

impl fmt::Display for MediaError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{} (FFmpeg error {})", self.message, self.code)
    }
}

impl std::error::Error for MediaError {}
