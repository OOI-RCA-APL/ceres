//! The API's error envelopes.
//!
//! Two shapes exist on the wire and both must be reproduced exactly. Typed errors
//! serialize as `{"__error__": true, "type": "<slug>", ...fields}` with their own status
//! codes. Handlers that fail without a typed error produce the bare HTTP envelope,
//! `{"__error__": true, "type": "http-error", "status": <code>}`, which is also what any
//! plain error response from a mounted service converts into.

use axum::http::{StatusCode, header};
use axum::response::{IntoResponse, Response};
use serde_json::{Map, Value};

/// A typed API error, serialized as the error envelope.
#[derive(Debug)]
pub struct ApiError {
    pub status: StatusCode,
    pub kind: &'static str,
    pub fields: Map<String, Value>,
}

/// Generate a constructor per typed error, named after its slug.
macro_rules! errors {
    ($($(#[$doc:meta])* $name:ident => $status:ident, $slug:literal;)*) => {
        impl ApiError {
            $($(#[$doc])* pub fn $name() -> Self {
                Self::new(StatusCode::$status, $slug)
            })*
        }
    };
}

errors! {
    not_found => NOT_FOUND, "not-found-error";
    not_authenticated => UNAUTHORIZED, "not-authenticated-error";
    not_permitted => FORBIDDEN, "not-permitted-error";
    bad_credentials => UNAUTHORIZED, "bad-credentials-error";
    authentication_disabled => FORBIDDEN, "authentication-disabled-error";
}

/// One validation problem, in the `{type, location, message}` shape of the wire.
#[derive(Debug)]
pub struct Problem {
    kind: String,
    location: Vec<Value>,
    message: String,
}

impl Problem {
    pub fn new(kind: impl Into<String>, location: &[&str], message: impl Into<String>) -> Self {
        Self {
            kind: kind.into(),
            location: location
                .iter()
                .map(|part| Value::String((*part).to_string()))
                .collect(),
            message: message.into(),
        }
    }

    pub fn into_json(self) -> Value {
        let mut body = Map::new();
        body.insert("type".to_string(), Value::String(self.kind));
        body.insert("location".to_string(), Value::Array(self.location));
        body.insert("message".to_string(), Value::String(self.message));
        Value::Object(body)
    }
}

impl ApiError {
    pub fn new(status: StatusCode, kind: &'static str) -> Self {
        Self {
            status,
            kind,
            fields: Map::new(),
        }
    }

    /// The bare HTTP envelope for a plain status code.
    pub fn http(status: StatusCode) -> Self {
        let mut error = Self::new(status, "http-error");
        error
            .fields
            .insert("status".to_string(), status.as_u16().into());
        error
    }

    fn body(&self) -> Vec<u8> {
        let mut envelope = Map::new();
        envelope.insert("__error__".to_string(), Value::Bool(true));
        envelope.insert("type".to_string(), Value::String(self.kind.to_string()));
        for (key, value) in &self.fields {
            envelope.insert(key.clone(), value.clone());
        }

        serde_json::to_vec(&envelope).expect("the envelope is always serializable")
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (
            self.status,
            [(header::CONTENT_TYPE, "application/json")],
            self.body(),
        )
            .into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn envelopes_serialize_in_wire_order() {
        assert_eq!(
            ApiError::not_found().body(),
            br#"{"__error__":true,"type":"not-found-error"}"#
        );
        assert_eq!(
            ApiError::http(StatusCode::METHOD_NOT_ALLOWED).body(),
            br#"{"__error__":true,"type":"http-error","status":405}"#
        );
    }
}
