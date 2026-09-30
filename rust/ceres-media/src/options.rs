use std::ffi::{CString, c_char, c_int};

use crate::MediaError;

/// FFmpeg options as the parallel key and value arrays the shim takes.
pub(crate) struct COptions {
    _strings: Vec<CString>,
    keys: Vec<*const c_char>,
    values: Vec<*const c_char>,
}

impl COptions {
    pub(crate) fn new(options: &[(&str, &str)]) -> Result<Self, MediaError> {
        let mut strings = Vec::with_capacity(options.len() * 2);
        for (key, value) in options {
            strings.push(c_string(key)?);
            strings.push(c_string(value)?);
        }
        // A `CString`'s heap buffer never moves, so the pointers outlive the pushes above.
        let keys = strings.iter().step_by(2).map(|key| key.as_ptr()).collect();
        let values = strings
            .iter()
            .skip(1)
            .step_by(2)
            .map(|value| value.as_ptr())
            .collect();
        Ok(Self {
            _strings: strings,
            keys,
            values,
        })
    }

    pub(crate) fn keys(&self) -> *const *const c_char {
        self.keys.as_ptr()
    }

    pub(crate) fn values(&self) -> *const *const c_char {
        self.values.as_ptr()
    }

    pub(crate) fn count(&self) -> c_int {
        c_int::try_from(self.keys.len()).expect("a handful of options")
    }
}

pub(crate) fn c_string(value: &str) -> Result<CString, MediaError> {
    CString::new(value).map_err(|_| MediaError::invalid(format!("{value:?} contains a NUL byte")))
}
