//! Authentication.
//!
//! Identities are stateless HS256 tokens carried in the `Authorization` header or a
//! cookie of the same name, the header winning when both arrive. A token holds the
//! user's ID in `sub`, its expiry in `exp`, and the impersonating administrator in
//! `imp` when another identity was taken on. Anything wrong with a token, its
//! signature, its claims, or the user it names, resolves to anonymous rather than an
//! error, matching the Python layer exactly.

use axum::http::{HeaderMap, header};
use ceres_entities::Timestamp;
use chrono::{DateTime, TimeDelta, Utc};
use serde_json::{Map, Value, json};
use uuid::Uuid;

use crate::error::ApiError;
use crate::host::{Host, HostError, UserRecord};

/// The authentication section's settings, absent when authentication is disabled.
pub struct AuthSettings {
    pub secret: String,
    pub duration: TimeDelta,
    pub allow_impersonate: bool,
}

/// A freshly minted token and its expiry.
pub struct MintedToken {
    pub token: String,
    pub expires: DateTime<Utc>,
}

/// The claims recovered from a presented token.
pub struct ParsedToken {
    pub token: String,
    pub user_id: Uuid,
    pub expires: DateTime<Utc>,
    pub impersonated_by: Option<Uuid>,
}

/// An authenticated identity, a parsed token joined with its user.
pub struct Identity {
    pub token: String,
    pub expires: DateTime<Utc>,
    pub user: UserRecord,
    pub impersonated_by: Option<Uuid>,
}

impl Identity {
    /// The identity's wire form.
    pub fn to_json(&self) -> Value {
        let mut body = Map::new();
        body.insert("token".to_string(), Value::String(self.token.clone()));
        body.insert("expires".to_string(), json!(Timestamp(self.expires)));
        body.insert("user".to_string(), self.user.payload.clone());
        body.insert(
            "impersonated_by".to_string(),
            match self.impersonated_by {
                Some(id) => Value::String(id.to_string()),
                None => Value::Null,
            },
        );
        Value::Object(body)
    }
}

/// Who a request comes from, resolved once per request.
///
/// The CLI control app and deployments with authentication unconfigured are
/// unrestricted, every permission gate short-circuits for them.
pub struct Actor {
    pub user: Option<UserRecord>,
    pub unrestricted: bool,
}

impl Actor {
    pub fn admin(&self) -> bool {
        self.unrestricted || self.user.as_ref().is_some_and(|user| user.admin)
    }

    pub fn authenticated(&self) -> bool {
        self.unrestricted || self.user.is_some()
    }
}

/// Mint a signed token for a user.
pub fn mint(
    user_id: Uuid,
    impersonated_by: Option<Uuid>,
    settings: &AuthSettings,
) -> Result<MintedToken, ApiError> {
    let expires = Utc::now() + settings.duration;
    let mut claims = Map::new();
    claims.insert("sub".to_string(), Value::String(user_id.to_string()));
    claims.insert("exp".to_string(), expires.timestamp().into());
    if let Some(id) = impersonated_by {
        claims.insert("imp".to_string(), Value::String(id.to_string()));
    }

    let token = jsonwebtoken::encode(
        &jsonwebtoken::Header::default(),
        &claims,
        &jsonwebtoken::EncodingKey::from_secret(settings.secret.as_bytes()),
    )
    .map_err(|_| ApiError::new(axum::http::StatusCode::INTERNAL_SERVER_ERROR, "error"))?;

    Ok(MintedToken { token, expires })
}

/// Recover the claims from a presented token, `None` for anything invalid.
pub fn parse(token: &str, secret: &str) -> Option<ParsedToken> {
    let mut validation = jsonwebtoken::Validation::new(jsonwebtoken::Algorithm::HS256);
    validation.leeway = 0;
    validation.required_spec_claims = ["sub", "exp"].iter().map(|s| s.to_string()).collect();

    let decoded = jsonwebtoken::decode::<Map<String, Value>>(
        token,
        &jsonwebtoken::DecodingKey::from_secret(secret.as_bytes()),
        &validation,
    )
    .ok()?;

    let claims = decoded.claims;
    let user_id: Uuid = claims.get("sub")?.as_str()?.parse().ok()?;
    let expires = DateTime::from_timestamp(claims.get("exp")?.as_i64()?, 0)?;
    let impersonated_by = match claims.get("imp") {
        Some(value) => Some(value.as_str()?.parse().ok()?),
        None => None,
    };

    Some(ParsedToken {
        token: token.to_string(),
        user_id,
        expires,
        impersonated_by,
    })
}

/// Extract the bearer token from the `Authorization` header or cookie, header first.
pub fn bearer_token(headers: &HeaderMap) -> Option<String> {
    let header = headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let value = header.or_else(|| authorization_cookie(headers))?;
    value.strip_prefix("Bearer ").map(str::to_string)
}

/// Find the `Authorization` cookie's value, unquoting it like Starlette does.
fn authorization_cookie(headers: &HeaderMap) -> Option<String> {
    for cookies in headers.get_all(header::COOKIE) {
        let cookies = cookies.to_str().ok()?;
        for pair in cookies.split(';') {
            let (name, value) = pair.trim().split_once('=')?;
            if name == "Authorization" {
                let value = value.trim_matches('"');
                return Some(value.replace("\\\"", "\""));
            }
        }
    }

    None
}

/// Resolve the current identity from a request's headers, anonymous on any failure.
pub async fn current_identity(
    settings: Option<&AuthSettings>,
    host: &dyn Host,
    headers: &HeaderMap,
) -> Result<Option<Identity>, HostError> {
    let Some(settings) = settings else {
        return Ok(None);
    };
    let Some(token) = bearer_token(headers) else {
        return Ok(None);
    };
    let Some(parsed) = parse(&token, &settings.secret) else {
        return Ok(None);
    };
    let Some(user) = host.user(parsed.user_id).await? else {
        return Ok(None);
    };

    Ok(Some(Identity {
        token: parsed.token,
        expires: parsed.expires,
        user,
        impersonated_by: parsed.impersonated_by,
    }))
}

/// Resolve the actor a request comes from.
pub async fn current_actor(
    settings: Option<&AuthSettings>,
    cli: bool,
    host: &dyn Host,
    headers: &HeaderMap,
) -> Result<Actor, HostError> {
    let identity = current_identity(settings, host, headers).await?;
    Ok(Actor {
        user: identity.map(|identity| identity.user),
        unrestricted: cli || settings.is_none(),
    })
}

/// Generate the actor gates, each returning its typed refusal.
macro_rules! gates {
    ($($(#[$doc:meta])* $name:ident($actor:ident) $body:block)*) => {
        $($(#[$doc])* pub fn $name($actor: &Actor) -> Result<(), ApiError> $body)*
    };
}

gates! {
    /// Require an enabled, authenticated user, unless the actor is unrestricted.
    require_authenticated(actor) {
        if actor.unrestricted {
            return Ok(());
        }

        match &actor.user {
            None => Err(ApiError::not_authenticated()),
            Some(user) if user.disabled => Err(ApiError::not_permitted()),
            Some(_) => Ok(()),
        }
    }

    /// Require an administrator, unless the actor is unrestricted.
    require_admin(actor) {
        require_authenticated(actor)?;
        if actor.unrestricted || actor.user.as_ref().is_some_and(|user| user.admin) {
            Ok(())
        } else {
            Err(ApiError::not_permitted())
        }
    }
}

/// Require the target user themselves or an administrator.
///
/// The target comes from the request path. A missing or malformed target refuses
/// rather than erring, matching the Python gate.
pub fn require_self_or_admin(actor: &Actor, target: Option<Uuid>) -> Result<(), ApiError> {
    require_authenticated(actor)?;
    if actor.admin() {
        return Ok(());
    }

    let Some(target) = target else {
        return Err(ApiError::not_permitted());
    };

    if actor.user.as_ref().is_some_and(|user| user.id == target) {
        Ok(())
    } else {
        Err(ApiError::not_permitted())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn settings() -> AuthSettings {
        AuthSettings {
            secret: "an-adequately-long-test-signing-secret".to_string(),
            duration: TimeDelta::minutes(30),
            allow_impersonate: false,
        }
    }

    #[test]
    fn tokens_round_trip_their_claims() {
        let user = Uuid::new_v4();
        let admin = Uuid::new_v4();
        let minted = mint(user, Some(admin), &settings()).unwrap();

        let parsed = parse(&minted.token, &settings().secret).unwrap();
        assert_eq!(parsed.user_id, user);
        assert_eq!(parsed.impersonated_by, Some(admin));
        assert_eq!(parsed.expires.timestamp(), minted.expires.timestamp());

        assert!(parse(&minted.token, "the-wrong-secret").is_none());
        assert!(parse("not-even-a-token", &settings().secret).is_none());
    }

    #[test]
    fn expired_tokens_resolve_to_anonymous() {
        let mut expired = settings();
        expired.duration = TimeDelta::minutes(-5);
        let minted = mint(Uuid::new_v4(), None, &expired).unwrap();
        assert!(parse(&minted.token, &expired.secret).is_none());
    }

    #[test]
    fn the_header_outranks_the_cookie() {
        let mut headers = HeaderMap::new();
        headers.insert(
            header::COOKIE,
            "Authorization=\"Bearer from-cookie\"".parse().unwrap(),
        );
        assert_eq!(bearer_token(&headers).as_deref(), Some("from-cookie"));

        headers.insert(header::AUTHORIZATION, "Bearer from-header".parse().unwrap());
        assert_eq!(bearer_token(&headers).as_deref(), Some("from-header"));

        headers.insert(header::AUTHORIZATION, "Basic other".parse().unwrap());
        assert_eq!(bearer_token(&headers), None);
    }

    #[test]
    fn gates_enforce_their_levels() {
        let anonymous = Actor {
            user: None,
            unrestricted: false,
        };
        let unrestricted = Actor {
            user: None,
            unrestricted: true,
        };
        let user = |admin: bool, disabled: bool| Actor {
            user: Some(UserRecord {
                id: Uuid::new_v4(),
                admin,
                disabled,
                payload: Value::Null,
            }),
            unrestricted: false,
        };

        assert!(require_authenticated(&anonymous).is_err());
        assert!(require_authenticated(&unrestricted).is_ok());
        assert!(require_authenticated(&user(false, false)).is_ok());
        assert!(require_authenticated(&user(false, true)).is_err());

        assert!(require_admin(&user(false, false)).is_err());
        assert!(require_admin(&user(true, false)).is_ok());
        assert!(require_admin(&unrestricted).is_ok());

        let actor = user(false, false);
        let own_id = actor.user.as_ref().unwrap().id;
        assert!(require_self_or_admin(&actor, Some(own_id)).is_ok());
        assert!(require_self_or_admin(&actor, Some(Uuid::new_v4())).is_err());
        assert!(require_self_or_admin(&actor, None).is_err());
        assert!(require_self_or_admin(&user(true, false), Some(Uuid::new_v4())).is_ok());
    }
}
