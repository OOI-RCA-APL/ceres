//! CLI error and exit semantics.
//!
//! Failure messages go to stderr, structured payloads are pretty-printed as JSON, and the
//! process exits with the carried status code.

use std::fmt;

/// An error that terminates the CLI with a status code and an optional message.
#[derive(Debug)]
pub struct Exit {
    pub status: i32,
    pub message: Option<String>,
}

impl Exit {
    /// Create a failure with exit status 1 and the given message.
    pub fn failed(message: impl Into<String>) -> Self {
        Self {
            status: 1,
            message: Some(prettify(message.into())),
        }
    }

    /// Create an exit with the given status and no message.
    pub fn status(status: i32) -> Self {
        Self {
            status,
            message: None,
        }
    }
}

/// Re-encode a message as indented JSON when it parses as JSON.
fn prettify(message: String) -> String {
    match serde_json::from_str::<serde_json::Value>(&message) {
        Ok(value) => serde_json::to_string_pretty(&value).unwrap_or(message),
        Err(_) => message,
    }
}

impl fmt::Display for Exit {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}", self.message.as_deref().unwrap_or(""))
    }
}

impl std::error::Error for Exit {}

pub type Result<T> = std::result::Result<T, Exit>;

/// Build an [`Exit`] failure from a format string.
macro_rules! failure {
    ($($argument:tt)*) => {
        $crate::error::Exit::failed(format!($($argument)*))
    };
}

/// Return early with an [`Exit`] failure built from a format string.
macro_rules! fail {
    ($($argument:tt)*) => {
        return Err($crate::error::failure!($($argument)*))
    };
}

pub(crate) use {fail, failure};
