//! What a user's password and email address become on their way into the database.
//!
//! These are the two columns a user write cannot store as it received them. A password
//! hashes with the database's configured parameters, and an email address normalizes.
//! A row written here must match the Python model's own writes byte for byte, or the
//! two sides disagree about what is stored.
//!
//! Both follow the write discipline the rest of the native path uses. Everything either
//! one refuses is refused before the transaction opens, and the refusal delegates rather
//! than reporting so Python produces the message and writes the row itself.

use argon2::password_hash::rand_core::{OsRng, RngCore};
use argon2::password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString};
use argon2::{Algorithm, Argon2, Params, Version};
use email_address::EmailAddress;
use serde_json::{Map, Value};
use unicode_normalization::UnicodeNormalization;

use crate::entities::EntityTable;

/// The Argon2id parameters a database's configuration asks for.
///
/// Held apart from the configuration types so this crate stays independent of them. The
/// caller reads them off the database config and refuses anything else, bcrypt being the
/// one other algorithm the configuration can name.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Argon2Params {
    pub time_cost: u32,
    pub memory_cost: u32,
    pub parallelism: u32,
    pub hash_length: usize,
    pub salt_length: usize,
}

/// The hashing a database configures, one of the two algorithms it can name.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Hashing {
    Argon2(Argon2Params),
    /// The bcrypt cost factor, its one parameter.
    Bcrypt(u32),
}

/// The credential rules one database's writes follow.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Credentials {
    hashing: Hashing,
}

impl Credentials {
    pub fn new(hashing: Hashing) -> Self {
        Self { hashing }
    }

    /// Apply the rules to one wire object bound for a table, the failure naming the
    /// refused column.
    ///
    /// Only a user carries either column so every other table passes through untouched.
    /// A refusal here happens while the object is still being read, before anything has
    /// been written, which lets the whole command delegate.
    pub fn apply(&self, table: EntityTable, object: &mut Map<String, Value>) -> Result<(), String> {
        if table != EntityTable::Users {
            return Ok(());
        }

        for (key, value) in object.iter_mut() {
            let Value::String(text) = value else {
                // A non-string in either column is the model's error to report.
                if key == "password" || key == "email" {
                    return Err(format!("The `{key}` value is not text."));
                }

                continue;
            };

            let replaced = match key.as_str() {
                "password" => self.password(text).ok_or_else(|| {
                    String::from(
                        "The `password` value is not one the model accepts, or could not \
                         be hashed.",
                    )
                }),
                "email" => normalize_email(text)
                    .ok_or_else(|| String::from("The `email` value is not a valid email address.")),
                _ => continue,
            }?;

            *value = Value::String(replaced);
        }

        Ok(())
    }

    /// Hash a password, or pass an already-hashed one through.
    ///
    /// A value that already reads as a password hash is stored as it arrived, which is
    /// what lets a dump of one database load into another. That is the manager's own
    /// rule, and a load file full of stored hashes depends on it.
    ///
    /// Anything else has to be a password the create model would have accepted, or the
    /// native path would store a hash of a value Python refuses outright.
    pub fn password(&self, value: &str) -> Option<String> {
        if is_password_hash(value) {
            return Some(value.to_string());
        }

        if !valid_password(value) {
            return None;
        }

        match self.hashing {
            Hashing::Argon2(parameters) => hash_argon2(value, parameters),
            Hashing::Bcrypt(cost) => hash_bcrypt(value, cost),
        }
    }
}

/// Whether a plaintext password is one the create model would take.
///
/// The only ceiling is bcrypt's 72-byte input limit, measured in bytes because that is
/// how bcrypt measures it. A passphrase is a good password so nothing narrower applies.
///
/// This is never reached by a stored hash. [`Credentials::password`] recognizes one first
/// and passes it through, which it has to since every hash is longer than this allows.
pub fn valid_password(value: &str) -> bool {
    !value.is_empty() && value.len() <= 72
}

/// Hash with Argon2id under the given parameters.
fn hash_argon2(value: &str, parameters: Argon2Params) -> Option<String> {
    let configured = Params::new(
        parameters.memory_cost,
        parameters.time_cost,
        parameters.parallelism,
        Some(parameters.hash_length),
    )
    .ok()?;
    let mut salt = vec![0u8; parameters.salt_length];
    OsRng.fill_bytes(&mut salt);
    let salt = SaltString::encode_b64(&salt).ok()?;

    Argon2::new(Algorithm::Argon2id, Version::V0x13, configured)
        .hash_password(value.as_bytes(), &salt)
        .ok()
        .map(|hash| hash.to_string())
}

/// Hash with bcrypt at the given cost.
///
/// The crate writes the `$2b$` prefix the Python library writes, and both salt from the
/// system generator so the two produce the same shape and verify each other's output.
fn hash_bcrypt(value: &str, cost: u32) -> Option<String> {
    bcrypt::hash(value, cost).ok()
}

/// Whether a password matches a stored bcrypt hash, `None` for any other algorithm.
pub fn verify_bcrypt(password: &str, hash: &str) -> Option<bool> {
    if !bcrypt_hash(hash) {
        return None;
    }

    bcrypt::verify(password, hash).ok()
}

/// Whether a password matches a stored Argon2 hash.
///
/// The parameters come out of the encoded string rather than from a configuration, which
/// lets a hash written under one configuration still verify after the parameters
/// are changed. A hash of any other algorithm answers `None`, leaving it to the caller.
pub fn verify_argon2(password: &str, hash: &str) -> Option<bool> {
    if !argon2_hash(hash) {
        return None;
    }

    let parsed = PasswordHash::new(hash).ok()?;
    Some(
        Argon2::default()
            .verify_password(password.as_bytes(), &parsed)
            .is_ok(),
    )
}

/// Whether a value already reads as a stored password hash.
///
/// The two patterns are the ones the Python data types validate against so a value this
/// accepts is one the model would have passed through rather than hashed again.
pub fn is_password_hash(value: &str) -> bool {
    bcrypt_hash(value) || argon2_hash(value)
}

/// `$2a$`, `$2b$`, or `$2y$` followed by exactly 56 characters.
fn bcrypt_hash(value: &str) -> bool {
    let Some(rest) = value.strip_prefix("$2") else {
        return false;
    };
    let Some(rest) = rest
        .strip_prefix(['a', 'y', 'b'])
        .and_then(|rest| rest.strip_prefix('$'))
    else {
        return false;
    };

    rest.chars().count() == 56
}

/// `$argon2{id,i,d}$v=<digits>$m=<digits>,t=<digits>,p=<digits>$<base64 and $>`.
fn argon2_hash(value: &str) -> bool {
    let Some(rest) = value.strip_prefix("$argon2") else {
        return false;
    };
    let Some(rest) = ["id", "i", "d"]
        .iter()
        .find_map(|variant| rest.strip_prefix(variant))
        .and_then(|rest| rest.strip_prefix("$v="))
    else {
        return false;
    };

    let Some((version, rest)) = rest.split_once("$m=") else {
        return false;
    };
    let Some((memory, rest)) = rest.split_once(",t=") else {
        return false;
    };
    let Some((time, rest)) = rest.split_once(",p=") else {
        return false;
    };
    let Some((parallelism, tail)) = rest.split_once('$') else {
        return false;
    };

    let digits = |text: &str| !text.is_empty() && text.chars().all(|c| c.is_ascii_digit());
    digits(version)
        && digits(memory)
        && digits(time)
        && digits(parallelism)
        && !tail.is_empty()
        && tail
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '/' | '$'))
}

/// The reserved names no address can be delivered to.
///
/// Every one of these is set aside by RFC 2606 or RFC 7686 for documentation, testing, or
/// onion routing so no address under them can receive mail.
pub const SPECIAL_USE_DOMAINS: &[&str] =
    &["arpa", "invalid", "local", "localhost", "onion", "test"];

/// Normalize an email address into the form Ceres stores, `None` for one it will not take.
///
/// This is the only definition of a valid address in the system. It is built from crates
/// rather than written out, `email_address` for the RFC 5322 grammar, `idna` for UTS-46
/// domain processing, and `unicode-normalization` for the local part, with only the
/// narrowing between them written here.
///
/// The stored form is what a lookup compares against so normalizing has to be
/// idempotent. Normalizing an already-stored address returns the same text so a filter
/// finds the row a create wrote.
///
/// Refused are display forms, quoted local parts, domain literals, single-label domains,
/// and the reserved names above, none of which name a mailbox Ceres can hold.
pub fn normalize_email(value: &str) -> Option<String> {
    // The whole address is capped the way SMTP caps a path.
    if value.len() > 254 {
        return None;
    }

    // Composing comes first so a decomposed `u` plus a combining diaeresis is the same
    // input as a composed `ü` from here on. It also has to precede parsing because the
    // grammar crate reads a combining mark as an invalid character.
    let composed: String = value.nfc().collect();
    let parsed: EmailAddress = composed.parse().ok()?;

    // A display form, `Ada <a@b.com>`, carries a name the stored column has nowhere to
    // put, and a quoted local part carries quoting the comparison would have to preserve.
    if !parsed.display_part().is_empty() {
        return None;
    }

    let local = parsed.local_part().to_string();
    if local.starts_with('"') || local.is_empty() || local.len() > 64 {
        return None;
    }

    // UTS-46 case-folds, composes, maps the label separators, and decodes punycode so a
    // domain written in ASCII and the same one written in its own script land together.
    let (domain, processed) = idna::domain_to_unicode(parsed.domain());
    processed.ok()?;

    let labels: Vec<&str> = domain.split('.').collect();
    let [.., last] = labels.as_slice() else {
        return None;
    };
    // A single-label domain is a local network name rather than a deliverable one, and a
    // domain literal fails the same test, its brackets being no label at all.
    if labels.len() < 2 || domain.len() > 253 {
        return None;
    }

    if labels
        .iter()
        .any(|label| label.is_empty() || label.starts_with('-') || label.ends_with('-'))
    {
        return None;
    }

    // A deliverable name ends in an alphabetic label, which rules out the numeric tail an
    // address parser otherwise reads out of an IP address.
    if last.chars().count() < 2 || last.chars().any(|c| !c.is_alphabetic()) {
        return None;
    }

    if SPECIAL_USE_DOMAINS.contains(&last.to_lowercase().as_str()) {
        return None;
    }

    // UTS-46 already lowered the domain so this is the local part's fold.
    Some(format!("{local}@{domain}").to_lowercase())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parameters() -> Hashing {
        Hashing::Argon2(Argon2Params {
            time_cost: 3,
            memory_cost: 65536,
            parallelism: 4,
            hash_length: 32,
            salt_length: 16,
        })
    }

    #[test]
    fn a_hash_carries_the_parameters_its_configuration_named() {
        // Argon2 reads its parameters back out of the encoded string so verifying a hash
        // proves nothing about which parameters produced it. Reading them off the string
        // is what catches a hash length written where a salt length belongs.
        let credentials = Credentials::new(Hashing::Argon2(Argon2Params {
            time_cost: 2,
            memory_cost: 8192,
            parallelism: 1,
            hash_length: 24,
            salt_length: 20,
        }));
        let hashed = credentials.password("secret").expect("a password hashes");

        assert!(
            hashed.starts_with("$argon2id$v=19$m=8192,t=2,p=1$"),
            "{hashed}"
        );
        assert!(is_password_hash(&hashed), "{hashed}");

        let parts: Vec<&str> = hashed.split('$').collect();
        let decode =
            |text: &str| argon2::password_hash::Output::b64_decode(text).map(|output| output.len());
        assert_eq!(
            argon2::password_hash::Salt::from_b64(parts[4])
                .map(|salt| salt.decode_b64(&mut [0u8; 64]).map(<[u8]>::len)),
            Ok(Ok(20)),
            "{hashed}"
        );
        assert_eq!(decode(parts[5]), Ok(24), "{hashed}");

        // The same password hashes differently every time because the salt is fresh.
        let again = credentials.password("secret").expect("a password hashes");
        assert_ne!(hashed, again);
    }

    #[test]
    fn a_stored_hash_passes_through_rather_than_hashing_again() {
        let credentials = Credentials::new(parameters());
        let stored = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaA";
        assert_eq!(credentials.password(stored).as_deref(), Some(stored));

        let bcrypt = format!("$2b${}", "x".repeat(56));
        assert_eq!(
            credentials.password(&bcrypt).as_deref(),
            Some(bcrypt.as_str())
        );

        // A value that only looks like one is a password, and hashes.
        let almost = "$2b$short";
        assert!(!is_password_hash(almost));
        assert!(
            credentials
                .password(almost)
                .is_some_and(|hashed| hashed != almost)
        );
    }

    #[test]
    fn an_email_normalizes_to_one_stored_form() {
        let stored = |value: &str| normalize_email(value).expect(value);

        // Case folds and the local part composes so the same mailbox written different
        // ways lands on one text.
        assert_eq!(stored("Ada@Example.COM"), "ada@example.com");
        assert_eq!(stored("a.b+tag@Gmail.com"), "a.b+tag@gmail.com");
        assert_eq!(
            stored("linus@kernel.example.co.uk"),
            "linus@kernel.example.co.uk"
        );

        // An internationalized domain stores in its own script whether it arrives that
        // way or as punycode, which makes the two forms the same address.
        assert_eq!(stored("a@münchen.de"), "a@münchen.de");
        assert_eq!(stored("a@xn--mnchen-3ya.de"), "a@münchen.de");
        assert_eq!(stored("A@MÜNCHEN.DE"), "a@münchen.de");
        assert_eq!(stored("a@例え.jp"), "a@例え.jp");
        assert_eq!(stored("üser@example.com"), "üser@example.com");

        // Normalizing is idempotent so a stored address compares equal to itself and a
        // filter finds the row a create wrote.
        for value in [
            "Ada@Example.COM",
            "a@xn--mnchen-3ya.de",
            "A@MÜNCHEN.DE",
            "üser@例え.jp",
        ] {
            let once = stored(value);
            assert_eq!(stored(&once), once, "{value:?}");
        }

        // A composed and a decomposed local part are the same mailbox.
        assert_eq!(
            stored("üser@example.com"),
            stored("u\u{308}ser@example.com")
        );

        for refused in [
            "",
            "nobody",
            "@example.com",
            "a@",
            // A single-label name is a local network's, not a deliverable mailbox.
            "a@localhost",
            "a@example",
            // Reserved names receive no mail whatever precedes them.
            "a@example.invalid",
            "a@host.local",
            "a@site.ONION",
            "a@-example.com",
            "a@example-.com",
            "a@example..com",
            // A numeric tail is an address, not a name.
            "a@example.c0m",
            "a@127.0.0.1",
            "a@[127.0.0.1]",
            ".a@example.com",
            "a.@example.com",
            "a..b@example.com",
            // Quoting and display names carry text the stored column cannot hold.
            "\"quoted local\"@example.com",
            "Ada <ada@example.com>",
            "a b@example.com",
            "a@exam ple.com",
        ] {
            assert_eq!(normalize_email(refused), None, "{refused:?}");
        }
    }

    #[test]
    fn only_a_user_carries_a_column_these_rules_touch() {
        let credentials = Credentials::new(parameters());
        let object = |json: &str| -> Map<String, Value> { serde_json::from_str(json).unwrap() };

        // A variable's own `value` column is untouched whatever it holds.
        let mut values = object(r#"{"address": "@a", "name": "password", "value": "plain"}"#);
        let before = values.clone();
        assert!(
            credentials
                .apply(EntityTable::Variables, &mut values)
                .is_ok()
        );
        assert_eq!(values, before);

        let mut user =
            object(r#"{"username": "ada", "email": "Ada@Example.com", "password": "pw"}"#);
        assert!(credentials.apply(EntityTable::Users, &mut user).is_ok());
        assert_eq!(user["email"], Value::String("ada@example.com".into()));
        assert!(is_password_hash(user["password"].as_str().unwrap()));

        // An address outside the subset refuses the whole write.
        let mut user = object(r#"{"username": "ada", "email": "a@localhost", "password": "pw"}"#);
        assert!(credentials.apply(EntityTable::Users, &mut user).is_err());

        // So does a column holding something other than text.
        let mut user = object(r#"{"username": "ada", "email": 5, "password": "pw"}"#);
        assert!(credentials.apply(EntityTable::Users, &mut user).is_err());
    }
}
