//! The authentication routes.
//!
//! Request bodies validate before configuration and identity checks, except for the
//! password change, where the authenticated gate runs first. The order is part of the
//! wire contract.

use std::sync::Arc;
use std::time::Duration;

use axum::Json;
use axum::body::Bytes;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode, header};
use axum::response::{IntoResponse, Response};
use serde_json::json;
use uuid::Uuid;

use crate::app::{AppState, Resolution};
use crate::auth::{AuthSettings, Gate, Identity};
use crate::body::Body;
use crate::cookie::{self, CookieType};
use crate::error::ApiError;
use crate::host::UserRecord;

/// How long a failed credential check stalls, mitigating brute-force attempts.
const WRONG_PASSWORD_DELAY: Duration = Duration::from_millis(2500);

impl AuthSettings {
    /// Mint an identity for a user and answer with it, optionally assigning the cookie.
    fn identity_response(
        &self,
        user: UserRecord,
        impersonated_by: Option<Uuid>,
        kind: Option<CookieType>,
    ) -> Result<Response, ApiError> {
        let minted = self.mint(user.id, impersonated_by)?;
        let identity = Identity {
            token: minted.token,
            expires: minted.expires,
            user,
            impersonated_by,
        };

        let mut response = Json(identity.to_json()).into_response();
        if let Some(kind) = kind {
            response.headers_mut().insert(
                header::SET_COOKIE,
                kind.assign(&identity.token, identity.expires),
            );
        }

        Ok(response)
    }
}

/// Return the caller's identity, or refuse when the request carries none.
pub(crate) async fn me(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    match state.identity(&headers).await? {
        Some(identity) => Ok(Json(identity.to_json()).into_response()),
        None => Err(ApiError::not_authenticated()),
    }
}

/// Report the optional authentication behavior the console adapts itself to.
pub(crate) async fn features(State(state): State<Arc<AppState>>) -> Response {
    let impersonate = state
        .auth
        .as_ref()
        .is_some_and(|settings| settings.allow_impersonate);
    Json(json!({"impersonate": impersonate})).into_response()
}

/// Authenticate a username and password, answering with a fresh identity.
pub(crate) async fn login(
    State(state): State<Arc<AppState>>,
    bytes: Bytes,
) -> Result<Response, ApiError> {
    let mut body = Body::parse(&bytes)?;
    let username = body.required_string("username");
    let password = body.required_string("password");
    let kind = body.cookie();
    body.finish()?;

    let Some(settings) = state.auth.as_ref() else {
        return Err(ApiError::authentication_disabled());
    };

    let (Some(username), Some(password)) = (username, password) else {
        unreachable!("finishing the body refused missing fields");
    };
    match state.host.verify_login(username, password).await? {
        Some(user) => settings.identity_response(user, None, kind),
        None => {
            tokio::time::sleep(WRONG_PASSWORD_DELAY).await;
            Err(ApiError::bad_credentials())
        }
    }
}

/// Issue a fresh identity for the current user.
///
/// A refreshed identity is the user's own, an impersonation marker never carries over.
pub(crate) async fn refresh(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    bytes: Bytes,
) -> Result<Response, ApiError> {
    let mut body = Body::parse(&bytes)?;
    let kind = body.cookie();
    body.finish()?;

    let Some(settings) = state.auth.as_ref() else {
        return Err(ApiError::authentication_disabled());
    };

    match state.identity(&headers).await? {
        Some(identity) => settings.identity_response(identity.user, None, kind),
        None => Err(ApiError::not_authenticated()),
    }
}

/// Delete the authorization cookie and answer with the identity that logged out.
pub(crate) async fn logout(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    match state.identity(&headers).await? {
        Some(identity) => {
            let mut response = Json(identity.to_json()).into_response();
            response
                .headers_mut()
                .insert(header::SET_COOKIE, cookie::delete());
            Ok(response)
        }
        None => Err(ApiError::not_authenticated()),
    }
}

/// Take on another user's identity.
///
/// The route reports itself missing rather than forbidden when the feature is off so a
/// default deployment has no trace of it to find. Chaining is prevented structurally,
/// the issued identity is the target's own so a second hop fails its admin gate.
pub(crate) async fn impersonate(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    bytes: Bytes,
) -> Result<Response, ApiError> {
    let mut body = Body::parse(&bytes)?;
    let target = body.required_uuid("user_id");
    let kind = body.cookie();
    body.finish()?;

    let Some(settings) = state.auth.as_ref() else {
        return Err(ApiError::authentication_disabled());
    };
    if !settings.allow_impersonate {
        return Err(ApiError::not_found());
    }

    let Some(identity) = state.identity(&headers).await? else {
        return Err(ApiError::not_authenticated());
    };
    if !identity.user.admin {
        return Err(ApiError::not_permitted());
    }

    let Some(target) = target else {
        unreachable!("finishing the body refused a missing target");
    };
    match state.host.user(target).await? {
        Some(user) => settings.identity_response(user, Some(identity.user.id), kind),
        None => Err(ApiError::not_found()),
    }
}

/// Change the caller's own password.
pub(crate) async fn change_password(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    bytes: Bytes,
) -> Result<Response, ApiError> {
    // The authenticated gate runs before body validation, which the wire contract
    // fixes, and a caller without a concrete user gets the bare envelope.
    let actor = state
        .admit(&headers, Gate::Authenticated, Resolution::Full)
        .await?;
    let Some(user) = actor.user else {
        return Err(ApiError::http(StatusCode::UNAUTHORIZED));
    };

    let mut body = Body::parse(&bytes)?;
    let old_password = body.required_string("old_password");
    let new_password = body.required_string("new_password");
    body.finish()?;

    let (Some(old_password), Some(new_password)) = (old_password, new_password) else {
        unreachable!("finishing the body refused missing fields");
    };
    match state
        .host
        .change_password(user.id, old_password, new_password)
        .await?
    {
        Some(updated) => Ok(Json(updated.payload).into_response()),
        None => {
            tokio::time::sleep(WRONG_PASSWORD_DELAY).await;
            Err(ApiError::bad_credentials())
        }
    }
}
