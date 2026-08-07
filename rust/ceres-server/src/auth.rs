//! Authentication.
//!
//! Identities are stateless HS256 tokens carried in the `Authorization` header or a
//! cookie of the same name, the header winning when both arrive. A token holds the
//! user's ID in `sub`, its expiry in `exp`, and the impersonating administrator in
//! `imp` when another identity was taken on. Anything wrong with a token, its
//! signature, its claims, or the user it names, resolves to anonymous rather than an
//! error, which is the contract's deliberate posture.

use axum::http::{HeaderMap, header};
use ceres_entities::Timestamp;
use chrono::{DateTime, TimeDelta, Utc};
use serde_json::{Map, Value, json};
use uuid::Uuid;

use crate::error::ApiError;
use crate::host::UserRecord;

/// The authentication section's settings, absent when authentication is disabled.
///
/// The signing and verifying keys derive from the secret once here, so minting and
/// parsing spend no time on key material per request.
pub struct AuthSettings {
    pub duration: TimeDelta,
    pub allow_impersonate: bool,
    encoding: jsonwebtoken::EncodingKey,
    decoding: jsonwebtoken::DecodingKey,
    validation: jsonwebtoken::Validation,
}

impl AuthSettings {
    pub fn new(secret: &str, duration: TimeDelta, allow_impersonate: bool) -> Self {
        let mut validation = jsonwebtoken::Validation::new(jsonwebtoken::Algorithm::HS256);
        validation.leeway = 0;
        validation.required_spec_claims = ["sub", "exp"].iter().map(|s| s.to_string()).collect();

        Self {
            duration,
            allow_impersonate,
            encoding: jsonwebtoken::EncodingKey::from_secret(secret.as_bytes()),
            decoding: jsonwebtoken::DecodingKey::from_secret(secret.as_bytes()),
            validation,
        }
    }

    /// Mint a signed token for a user.
    pub fn mint(
        &self,
        user_id: Uuid,
        impersonated_by: Option<Uuid>,
    ) -> Result<MintedToken, ApiError> {
        let expires = Utc::now() + self.duration;
        let mut claims = Map::new();
        claims.insert("sub".to_string(), Value::String(user_id.to_string()));
        claims.insert("exp".to_string(), expires.timestamp().into());
        if let Some(id) = impersonated_by {
            claims.insert("imp".to_string(), Value::String(id.to_string()));
        }

        let token = jsonwebtoken::encode(&jsonwebtoken::Header::default(), &claims, &self.encoding)
            .map_err(|_| ApiError::new(axum::http::StatusCode::INTERNAL_SERVER_ERROR, "error"))?;

        Ok(MintedToken { token, expires })
    }

    /// Recover the claims from a presented token, `None` for anything invalid.
    pub fn parse(&self, token: &str) -> Option<ParsedToken> {
        let decoded =
            jsonwebtoken::decode::<Map<String, Value>>(token, &self.decoding, &self.validation)
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

    /// Require an enabled, authenticated user, unless the actor is unrestricted.
    pub fn require_authenticated(&self) -> Result<(), ApiError> {
        if self.unrestricted {
            return Ok(());
        }

        match &self.user {
            None => Err(ApiError::not_authenticated()),
            Some(user) if user.disabled => Err(ApiError::not_permitted()),
            Some(_) => Ok(()),
        }
    }

    /// Require an administrator, unless the actor is unrestricted.
    pub fn require_admin(&self) -> Result<(), ApiError> {
        self.require_authenticated()?;
        if self.admin() {
            Ok(())
        } else {
            Err(ApiError::not_permitted())
        }
    }

    /// Require the target user themselves or an administrator.
    ///
    /// The target comes from the request path. A missing or malformed target refuses
    /// rather than erring, matching the Python gate.
    pub fn require_self_or_admin(&self, target: Option<Uuid>) -> Result<(), ApiError> {
        self.require_authenticated()?;
        if self.admin() {
            return Ok(());
        }

        let Some(target) = target else {
            return Err(ApiError::not_permitted());
        };

        if self.user.as_ref().is_some_and(|user| user.id == target) {
            Ok(())
        } else {
            Err(ApiError::not_permitted())
        }
    }
}

/// Who a route admits.
#[derive(Clone, Copy)]
pub enum Gate {
    /// Anyone, the operation applies its own rules to the actor.
    Open,
    Authenticated,
    Admin,
    /// The user the named path parameter identifies, or an administrator.
    SelfOrAdmin(&'static str),
}

impl Gate {
    /// Admit or refuse an actor, the self-or-admin target read from named path values.
    ///
    /// Only the dispatch table's routes gate on a path parameter, so every other caller
    /// passes no values and admits on the actor alone.
    pub fn admit<'a>(
        self,
        actor: &Actor,
        mut path_values: impl Iterator<Item = (&'static str, &'a str)>,
    ) -> Result<(), ApiError> {
        match self {
            Self::Open => Ok(()),
            Self::Authenticated => actor.require_authenticated(),
            Self::Admin => actor.require_admin(),
            Self::SelfOrAdmin(parameter) => {
                let target = path_values
                    .find(|(name, _)| *name == parameter)
                    .and_then(|(_, value)| value.parse().ok());
                actor.require_self_or_admin(target)
            }
        }
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    fn settings() -> AuthSettings {
        AuthSettings::new(
            "an-adequately-long-test-signing-secret",
            TimeDelta::minutes(30),
            false,
        )
    }

    #[test]
    fn tokens_round_trip_their_claims() {
        let user = Uuid::new_v4();
        let admin = Uuid::new_v4();
        let minted = settings().mint(user, Some(admin)).unwrap();

        let parsed = settings().parse(&minted.token).unwrap();
        assert_eq!(parsed.user_id, user);
        assert_eq!(parsed.impersonated_by, Some(admin));
        assert_eq!(parsed.expires.timestamp(), minted.expires.timestamp());

        let wrong = AuthSettings::new("the-wrong-secret", TimeDelta::minutes(30), false);
        assert!(wrong.parse(&minted.token).is_none());
        assert!(settings().parse("not-even-a-token").is_none());
    }

    #[test]
    fn expired_tokens_resolve_to_anonymous() {
        let expired = AuthSettings::new(
            "an-adequately-long-test-signing-secret",
            TimeDelta::minutes(-5),
            false,
        );
        let minted = expired.mint(Uuid::new_v4(), None).unwrap();
        assert!(expired.parse(&minted.token).is_none());
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

        assert!(anonymous.require_authenticated().is_err());
        assert!(unrestricted.require_authenticated().is_ok());
        assert!(user(false, false).require_authenticated().is_ok());
        assert!(user(false, true).require_authenticated().is_err());

        assert!(user(false, false).require_admin().is_err());
        assert!(user(true, false).require_admin().is_ok());
        assert!(unrestricted.require_admin().is_ok());

        let actor = user(false, false);
        let own_id = actor.user.as_ref().unwrap().id;
        assert!(actor.require_self_or_admin(Some(own_id)).is_ok());
        assert!(actor.require_self_or_admin(Some(Uuid::new_v4())).is_err());
        assert!(actor.require_self_or_admin(None).is_err());
        assert!(
            user(true, false)
                .require_self_or_admin(Some(Uuid::new_v4()))
                .is_ok()
        );
    }
}
