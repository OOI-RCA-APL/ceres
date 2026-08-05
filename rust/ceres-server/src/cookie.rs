//! The authorization cookie.
//!
//! Login-family routes can set the token as a cookie named `Authorization`, holding the
//! same `Bearer` value the header carries. The attribute set and order reproduce the
//! Python layer's responses byte for byte, quoted value, `expires` in HTTP date form,
//! `Path=/`, `SameSite=lax`, plus `HttpOnly` and `Secure` when the caller asked for the
//! secure variant.

use axum::http::HeaderValue;
use chrono::{DateTime, Utc};

use crate::error::Problem;

/// Whether the cookie should use secure, HTTPS-only settings.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum CookieType {
    Insecure,
    Secure,
}

impl CookieType {
    /// Parse the wire form, reporting the same problem the Python layer would.
    pub fn parse(value: &str, location: &[&str]) -> Result<Self, Problem> {
        match value {
            "insecure" => Ok(Self::Insecure),
            "secure" => Ok(Self::Secure),
            _ => Err(Problem::new(
                "enum",
                location,
                "Input should be 'insecure' or 'secure'",
            )),
        }
    }

    /// The `Set-Cookie` value assigning a token.
    pub fn assign(self, token: &str, expires: DateTime<Utc>) -> HeaderValue {
        let expires = http_date(expires);
        let value = match self {
            Self::Insecure => {
                format!("Authorization=\"Bearer {token}\"; expires={expires}; Path=/; SameSite=lax")
            }
            Self::Secure => format!(
                "Authorization=\"Bearer {token}\"; expires={expires}; HttpOnly; Path=/; \
                 SameSite=lax; Secure"
            ),
        };

        HeaderValue::from_str(&value).expect("cookie values hold no invalid header bytes")
    }
}

fn http_date(moment: DateTime<Utc>) -> String {
    moment.format("%a, %d %b %Y %H:%M:%S GMT").to_string()
}

/// The `Set-Cookie` value deleting the authorization cookie.
pub fn delete() -> HeaderValue {
    let expires = http_date(Utc::now());
    let value = format!("Authorization=\"\"; expires={expires}; Max-Age=0; Path=/; SameSite=lax");
    HeaderValue::from_str(&value).expect("cookie values hold no invalid header bytes")
}

#[cfg(test)]
mod tests {
    use chrono::TimeZone;

    use super::*;

    #[test]
    fn cookies_render_in_wire_form() {
        let expires = Utc.with_ymd_and_hms(2026, 7, 30, 0, 44, 14).unwrap();
        assert_eq!(
            CookieType::Insecure.assign("abc", expires),
            "Authorization=\"Bearer abc\"; expires=Thu, 30 Jul 2026 00:44:14 GMT; Path=/; \
             SameSite=lax"
        );
        assert_eq!(
            CookieType::Secure.assign("abc", expires),
            "Authorization=\"Bearer abc\"; expires=Thu, 30 Jul 2026 00:44:14 GMT; HttpOnly; \
             Path=/; SameSite=lax; Secure"
        );

        let deletion = delete().to_str().unwrap().to_string();
        assert!(deletion.starts_with("Authorization=\"\"; expires="));
        assert!(deletion.ends_with("GMT; Max-Age=0; Path=/; SameSite=lax"));
    }
}
