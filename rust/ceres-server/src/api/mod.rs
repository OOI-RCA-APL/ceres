//! The API's route families.
//!
//! One module per family, mirroring how the routes group on the wire. Handlers parse
//! and gate natively, reach the engine through the host for anything it owns, and
//! answer in the exact wire shapes the Python application produced.

pub(crate) mod auth;
pub(crate) mod config;
pub(crate) mod dispatch;
pub(crate) mod records;
pub(crate) mod schema;
pub(crate) mod streams;

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

/// Describe every route the server serves, for the OpenAPI document.
pub(crate) fn documented_routes() -> Vec<schema::Documented> {
    use utoipa::openapi::HttpMethod;

    use crate::api::schema::Documented;

    /// Write the routes whose handlers are hand-written rather than declared.
    macro_rules! described {
        ($($method:ident $path:expr => $summary:expr, $tag:literal
            $(, params($($parameter:literal),+))? $(, open: $open:literal)?;)*) => {
            vec![$(Documented {
                method: HttpMethod::$method,
                path: $path,
                summary: $summary,
                parameters: &[$($($parameter),+)?],
                secured: !(false $(|| $open)?),
                tag: $tag,
            }),*]
        };
    }

    let mut routes = described! {
        Get "/api/alive" => "Report that the server is alive.", "engine", open: true;
        Get "/api" => "Redirect to the OpenAPI document.", "engine", open: true;
        Get "/api/openapi.json" => "Serve the OpenAPI document.", "engine", open: true;
        Post "/api/auth/login" => "Authenticate and receive an identity.", "auth", open: true;
        Post "/api/auth/refresh" => "Reissue the caller's identity.", "auth", open: true;
        Post "/api/auth/logout" => "Delete the authorization cookie.", "auth", open: true;
        Post "/api/auth/impersonate" => "Take on another user's identity.", "auth", open: true;
        Post "/api/auth/change-password" => "Change the caller's password.", "auth";
        Get "/api/auth/me" => "Return the caller's identity.", "auth", open: true;
        Get "/api/auth/features" => "Report optional authentication behavior.", "auth", open: true;
        Get "/api/config" => "Serve the whole configuration.", "config";
        Get "/api/config/service" => "Serve the service configuration.", "config";
        Get "/api/config/server" => "Serve the server configuration.", "config";
        Get "/api/config/database" => "Serve the database configuration.", "config";
        Get "/api/config/console" => "Serve the console configuration.", "config", open: true;
        Get "/api/statuses" => "List component statuses, or stream them.", "statuses";
    };

    macro_rules! record_tables {
        ($($name:literal),*) => {
            $(routes.extend(described! {
                Get concat!("/api/", $name) => concat!("List ", $name, ", or stream them."), $name;
                Get concat!("/api/", $name, "/count") => concat!("Count ", $name, "."), $name;
                Get concat!("/api/", $name, "/{id}") => concat!("Fetch one of the ", $name, "."),
                    $name, params("id");
            });)*
        };
    }

    record_tables!("messages", "particles", "alerts", "logs");
    routes.extend(dispatch::documented());
    routes.extend(streams::documented());
    routes
}
