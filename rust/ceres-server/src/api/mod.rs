//! The API's route families.
//!
//! One module per family, mirroring how the routes group on the wire. Handlers parse
//! and gate natively, reach the engine through the host for anything it owns, and
//! answer in the exact wire shapes the Python application produced.

pub(crate) mod auth;
pub(crate) mod config;
pub(crate) mod dispatch;
pub(crate) mod records;

/// Unwrap a fallible expression or answer with its response.
macro_rules! attempt {
    ($result:expr) => {
        match $result {
            Ok(value) => value,
            Err(refusal) => return axum::response::IntoResponse::into_response(refusal),
        }
    };
}

pub(crate) use attempt;
