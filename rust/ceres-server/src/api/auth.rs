//! The authentication routes.
//!
//! Request bodies validate before configuration and identity checks, matching the
//! framework order they replace, except for the password change, whose authenticated
//! gate ran first as a route dependency there too.

use std::sync::Arc;
use std::time::Duration;

use axum::body::Bytes;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode, header};
use axum::response::{IntoResponse, Response};
use serde_json::json;
use uuid::Uuid;

use crate::api::attempt;
use crate::app::{AppState, json_response};
use crate::auth::{self, AuthSettings, require_authenticated};
use crate::body::Body;
use crate::cookie::{self, CookieType};
use crate::error::ApiError;
use crate::host::UserRecord;

/// How long a failed credential check stalls, mitigating brute-force attempts.
const WRONG_PASSWORD_DELAY: Duration = Duration::from_millis(2500);

/// Mint an identity for a user and answer with it, optionally assigning the cookie.
fn identity_response(
    user: UserRecord,
    impersonated_by: Option<Uuid>,
    settings: &AuthSettings,
    kind: Option<CookieType>,
) -> Response {
    let minted = attempt!(auth::mint(user.id, impersonated_by, settings));
    let identity = auth::Identity {
        token: minted.token,
        expires: minted.expires,
        user,
        impersonated_by,
    };

    let mut response = json_response(identity.to_json());
    if let Some(kind) = kind {
        response.headers_mut().insert(
            header::SET_COOKIE,
            cookie::assign(&identity.token, identity.expires, kind),
        );
    }

    response
}

/// Return the caller's identity, or refuse when the request carries none.
pub(crate) async fn me(State(state): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    match state.identity(&headers).await {
        Ok(Some(identity)) => json_response(identity.to_json()),
        Ok(None) => ApiError::not_authenticated().into_response(),
        Err(error) => error.into_response(),
    }
}

/// Report the optional authentication behavior the console adapts itself to.
pub(crate) async fn features(State(state): State<Arc<AppState>>) -> Response {
    let impersonate = state
        .auth
        .as_ref()
        .is_some_and(|settings| settings.allow_impersonate);
    json_response(json!({"impersonate": impersonate}))
}

/// Authenticate a username and password, answering with a fresh identity.
pub(crate) async fn login(State(state): State<Arc<AppState>>, bytes: Bytes) -> Response {
    let mut body = attempt!(Body::parse(&bytes));
    let username = body.required_string("username");
    let password = body.required_string("password");
    let kind = body.cookie();
    attempt!(body.finish());

    let Some(settings) = state.auth.as_ref() else {
        return ApiError::authentication_disabled().into_response();
    };

    let (Some(username), Some(password)) = (username, password) else {
        unreachable!("finishing the body refused missing fields");
    };
    match state.host.verify_login(username, password).await {
        Ok(Some(user)) => identity_response(user, None, settings, kind),
        Ok(None) => {
            tokio::time::sleep(WRONG_PASSWORD_DELAY).await;
            ApiError::bad_credentials().into_response()
        }
        Err(error) => error.into_response(),
    }
}

/// Issue a fresh identity for the current user.
///
/// A refreshed identity is the user's own, an impersonation marker never carries over.
pub(crate) async fn refresh(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    bytes: Bytes,
) -> Response {
    let mut body = attempt!(Body::parse(&bytes));
    let kind = body.cookie();
    attempt!(body.finish());

    let Some(settings) = state.auth.as_ref() else {
        return ApiError::authentication_disabled().into_response();
    };

    match state.identity(&headers).await {
        Ok(Some(identity)) => identity_response(identity.user, None, settings, kind),
        Ok(None) => ApiError::not_authenticated().into_response(),
        Err(error) => error.into_response(),
    }
}

/// Delete the authorization cookie and answer with the identity that logged out.
pub(crate) async fn logout(State(state): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    match state.identity(&headers).await {
        Ok(Some(identity)) => {
            let mut response = json_response(identity.to_json());
            response
                .headers_mut()
                .insert(header::SET_COOKIE, cookie::delete());
            response
        }
        Ok(None) => ApiError::not_authenticated().into_response(),
        Err(error) => error.into_response(),
    }
}

/// Take on another user's identity.
///
/// The route reports itself missing rather than forbidden when the feature is off, so a
/// default deployment has no trace of it to find. Chaining is prevented structurally,
/// the issued identity is the target's own, so a second hop fails its admin gate.
pub(crate) async fn impersonate(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    bytes: Bytes,
) -> Response {
    let mut body = attempt!(Body::parse(&bytes));
    let target = body.required_uuid("user_id");
    let kind = body.cookie();
    attempt!(body.finish());

    let Some(settings) = state.auth.as_ref() else {
        return ApiError::authentication_disabled().into_response();
    };
    if !settings.allow_impersonate {
        return ApiError::not_found().into_response();
    }

    let identity = match state.identity(&headers).await {
        Ok(Some(identity)) => identity,
        Ok(None) => return ApiError::not_authenticated().into_response(),
        Err(error) => return error.into_response(),
    };
    if !identity.user.admin {
        return ApiError::not_permitted().into_response();
    }

    let Some(target) = target else {
        unreachable!("finishing the body refused a missing target");
    };
    match state.host.user(target).await {
        Ok(Some(user)) => identity_response(user, Some(identity.user.id), settings, kind),
        Ok(None) => ApiError::not_found().into_response(),
        Err(error) => error.into_response(),
    }
}

/// Change the caller's own password.
pub(crate) async fn change_password(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    bytes: Bytes,
) -> Response {
    // The authenticated gate runs before body validation, matching the route dependency
    // it replaces, and a caller without a concrete user gets the bare envelope.
    let actor = attempt!(state.actor(&headers).await);
    attempt!(require_authenticated(&actor));
    let Some(user) = actor.user else {
        return ApiError::http(StatusCode::UNAUTHORIZED).into_response();
    };

    let mut body = attempt!(Body::parse(&bytes));
    let old_password = body.required_string("old_password");
    let new_password = body.required_string("new_password");
    attempt!(body.finish());

    let (Some(old_password), Some(new_password)) = (old_password, new_password) else {
        unreachable!("finishing the body refused missing fields");
    };
    match state
        .host
        .change_password(user.id, old_password, new_password)
        .await
    {
        Ok(Some(updated)) => json_response(updated.payload),
        Ok(None) => {
            tokio::time::sleep(WRONG_PASSWORD_DELAY).await;
            ApiError::bad_credentials().into_response()
        }
        Err(error) => error.into_response(),
    }
}
