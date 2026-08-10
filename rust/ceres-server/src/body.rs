//! Request body parsing with validation problems.
//!
//! Bodies parse into JSON and extract field by field, collecting every problem rather
//! than stopping at the first, in the `{type, location, message}` shape the wire
//! contract fixes. Message text follows Pydantic's phrasing for the common cases
//! because the contract's error bodies are pinned to it.

use serde_json::{Map, Value};
use uuid::Uuid;

use crate::error::{ApiError, Problem};

/// The fields of a JSON object body, collecting problems as they extract.
#[derive(Debug)]
pub struct Body {
    fields: Map<String, Value>,
    problems: Vec<Problem>,
}

impl Body {
    /// Parse a request body, refusing anything but a JSON object.
    pub fn parse(bytes: &[u8]) -> Result<Self, ApiError> {
        let value: Value = serde_json::from_slice(bytes).map_err(|error| {
            ApiError::validation(vec![Problem::new(
                "json_invalid",
                &["body"],
                format!("Invalid JSON: {error}"),
            )])
        })?;
        match value {
            Value::Object(fields) => Ok(Self {
                fields,
                problems: Vec::new(),
            }),
            _ => Err(ApiError::validation(vec![Problem::new(
                "model_attributes_type",
                &["body"],
                "Input should be a valid dictionary or object to extract fields from",
            )])),
        }
    }

    /// Finish extraction, refusing with the collected problems when any exist.
    pub fn finish(self) -> Result<(), ApiError> {
        if self.problems.is_empty() {
            Ok(())
        } else {
            Err(ApiError::validation(self.problems))
        }
    }

    pub fn required_string(&mut self, field: &'static str) -> Option<String> {
        match self.fields.get(field) {
            None | Some(Value::Null) => {
                self.problems
                    .push(Problem::new("missing", &["body", field], "Field required"));
                None
            }
            Some(Value::String(value)) => Some(value.clone()),
            Some(_) => {
                self.problems.push(Problem::new(
                    "string_type",
                    &["body", field],
                    "Input should be a valid string",
                ));
                None
            }
        }
    }

    pub fn optional_string(&mut self, field: &'static str) -> Option<String> {
        match self.fields.get(field) {
            None | Some(Value::Null) => None,
            Some(Value::String(value)) => Some(value.clone()),
            Some(_) => {
                self.problems.push(Problem::new(
                    "string_type",
                    &["body", field],
                    "Input should be a valid string",
                ));
                None
            }
        }
    }

    pub fn required_uuid(&mut self, field: &'static str) -> Option<Uuid> {
        let text = self.required_string(field)?;
        match text.parse() {
            Ok(id) => Some(id),
            Err(_) => {
                self.problems.push(Problem::new(
                    "uuid_parsing",
                    &["body", field],
                    "Input should be a valid UUID",
                ));
                None
            }
        }
    }

    /// Extract the optional cookie type the login-family routes accept.
    pub fn cookie(&mut self) -> Option<crate::cookie::CookieType> {
        let text = self.optional_string("cookie")?;
        match crate::cookie::CookieType::parse(&text, &["body", "cookie"]) {
            Ok(kind) => Some(kind),
            Err(problem) => {
                self.problems.push(problem);
                None
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn problems_collect_across_fields() {
        let mut body = Body::parse(br#"{"password": 5, "cookie": "wrong"}"#).unwrap();
        let username = body.required_string("username");
        let password = body.required_string("password");
        let cookie = body.cookie();
        assert!(username.is_none() && password.is_none() && cookie.is_none());

        let error = body.finish().unwrap_err();
        let problems = error.fields.get("problems").unwrap().as_array().unwrap();
        let kinds: Vec<_> = problems
            .iter()
            .map(|problem| problem["type"].as_str().unwrap())
            .collect();
        assert_eq!(kinds, ["missing", "string_type", "enum"]);
        assert_eq!(
            problems[0]["location"],
            serde_json::json!(["body", "username"])
        );
    }

    #[test]
    fn invalid_json_refuses_with_a_problem() {
        let error = Body::parse(b"not json").unwrap_err();
        assert_eq!(error.status, axum::http::StatusCode::UNPROCESSABLE_ENTITY);
    }
}
