//! What a user's password and email address become on their way into the database.
//!
//! These are the two columns a user write cannot store as it received them. A password
//! hashes with the database's configured parameters, and an email address normalizes,
//! so a row written here has to come out of the Python model's own writes byte for byte
//! or the two disagree about what is stored.
//!
//! Both follow the write discipline the rest of the native path uses. Everything either
//! one refuses is refused before the transaction opens, and the refusal delegates rather
//! than reporting, so Python produces the message and writes the row itself.

use argon2::password_hash::rand_core::{OsRng, RngCore};
use argon2::password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString};
use argon2::{Algorithm, Argon2, Params, Version};
use email_address::EmailAddress;
use serde_json::{Map, Value};

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

/// The credential rules one database's writes follow.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Credentials {
    hashing: Argon2Params,
}

impl Credentials {
    pub fn new(hashing: Argon2Params) -> Self {
        Self { hashing }
    }

    /// Apply the rules to one wire object bound for a table, `false` to refuse it.
    ///
    /// Only a user carries either column, so every other table passes through untouched.
    /// A refusal here happens while the object is still being read, before anything has
    /// been written, which is what lets the whole command delegate.
    pub fn apply(&self, table: EntityTable, object: &mut Map<String, Value>) -> bool {
        if table != EntityTable::Users {
            return true;
        }

        for (key, value) in object.iter_mut() {
            let Value::String(text) = value else {
                // A non-string in either column is the model's error to report.
                if key == "password" || key == "email" {
                    return false;
                }

                continue;
            };

            let replaced = match key.as_str() {
                "password" => self.password(text),
                "email" => normalize_email(text),
                _ => continue,
            };
            let Some(replaced) = replaced else {
                return false;
            };

            *value = Value::String(replaced);
        }

        true
    }

    /// Hash a password, or pass an already-hashed one through.
    ///
    /// A value that already reads as a password hash is stored as it arrived, which is
    /// what lets a dump of one database load into another. That is the manager's own
    /// rule, and a load file full of stored hashes depends on it.
    pub fn password(&self, value: &str) -> Option<String> {
        if is_password_hash(value) {
            return Some(value.to_string());
        }

        let parameters = Params::new(
            self.hashing.memory_cost,
            self.hashing.time_cost,
            self.hashing.parallelism,
            Some(self.hash_length()),
        )
        .ok()?;
        let mut salt = vec![0u8; self.hashing.salt_length];
        OsRng.fill_bytes(&mut salt);
        let salt = SaltString::encode_b64(&salt).ok()?;

        Argon2::new(Algorithm::Argon2id, Version::V0x13, parameters)
            .hash_password(value.as_bytes(), &salt)
            .ok()
            .map(|hash| hash.to_string())
    }

    fn hash_length(&self) -> usize {
        self.hashing.hash_length
    }
}

/// Whether a password matches a stored Argon2 hash.
///
/// The parameters come out of the encoded string rather than from a configuration, which
/// is what lets a hash written under one configuration still verify after the parameters
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
/// The two patterns are the ones the Python data types validate against, so a value this
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

/// The reserved names no address can be delivered to, which the validator library
/// refuses and this subset therefore refuses too.
///
/// Kept in the library's own order and spelling. `SPECIAL_USE_DOMAIN_NAMES` is where it
/// lives on the Python side, and the parity suite compares the two.
pub const SPECIAL_USE_DOMAINS: &[&str] =
    &["arpa", "invalid", "local", "localhost", "onion", "test"];

/// Normalize an email address, `None` for anything outside the subset this understands.
///
/// The grammar belongs to the `email_address` crate, which parses RFC 5322 addresses.
/// What is left here is the narrowing, the difference between what that crate admits and
/// what the Python model stores.
///
/// The Python model validates through the `email_validator` library and then lowercases
/// the whole result. That library is stricter than RFC 5322 in some places, refusing
/// undeliverable names, and it rewrites the address in others, decoding an
/// internationalized domain back to Unicode. Neither library is the other, so the subset
/// admitted here is the plain ASCII intersection where normalizing IS lowercasing.
///
/// The narrowing runs one way on purpose. An address refused here delegates, which costs
/// a process start and nothing else. One accepted here that the model would have refused,
/// or would have stored differently, is a row written wrong, so the parity suite sweeps
/// that direction alone.
pub fn normalize_email(value: &str) -> Option<String> {
    let parsed: EmailAddress = value.parse().ok()?;

    // Anything non-ASCII is an internationalized address the model rewrites rather than
    // lowercases, in the local part through Unicode normalization and in the domain
    // through IDNA. Holding to ASCII is what makes lowercasing the whole answer.
    if !value.is_ascii() {
        return None;
    }

    // A quoted local part is one the model refuses outright. The crate keeps the quotes,
    // so their absence is the test.
    let local = parsed.local_part();
    if local.starts_with('"') {
        return None;
    }

    // The crate reads a display form, `Ada <a@b.com>`, as an address with a name on it.
    // The model takes no such thing, and lowercasing one would store the whole string.
    if !parsed.display_part().is_empty() {
        return None;
    }

    // A domain is at least two labels, because the model reads a bare single-label name
    // as special-use or undeliverable. A domain literal, `a@[127.0.0.1]`, falls out of
    // the same checks, its brackets and digits being no label at all.
    let labels: Vec<&str> = parsed.domain().split('.').collect();
    let [.., last] = labels.as_slice() else {
        return None;
    };
    if labels.len() < 2 {
        return None;
    }

    // A hostname label is letters, digits, and inner hyphens. The crate reads the wider
    // RFC 5322 domain, which admits an underscore among other things, and the model does
    // not, so the narrower reading is the one that holds here.
    //
    // A punycode label is refused for a different reason. It is an internationalized name
    // written in ASCII, which the model decodes back to its Unicode form rather than
    // storing as it arrived.
    let hostname = |label: &&str| {
        !label.is_empty()
            && label.len() <= 63
            && !label.starts_with('-')
            && !label.ends_with('-')
            && !label.starts_with("xn--")
            && label.chars().all(|c| c.is_ascii_alphanumeric() || c == '-')
    };
    if !labels.iter().all(hostname) {
        return None;
    }

    // A deliverable name ends in an alphabetic label of at least two characters, which
    // rules out the numeric tails an address parser will otherwise take.
    if last.len() < 2 || !last.chars().all(|c| c.is_ascii_alphabetic()) {
        return None;
    }

    // The model refuses an address whose domain ends in a special-use name, because none
    // of them can receive mail. The parity suite holds this list against the library's
    // own, so a name added there fails the suite rather than passing silently.
    if SPECIAL_USE_DOMAINS.contains(&last.to_lowercase().as_str()) {
        return None;
    }

    Some(value.to_lowercase())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parameters() -> Argon2Params {
        Argon2Params {
            time_cost: 3,
            memory_cost: 65536,
            parallelism: 4,
            hash_length: 32,
            salt_length: 16,
        }
    }

    #[test]
    fn a_hash_carries_the_parameters_its_configuration_named() {
        // Argon2 reads its parameters back out of the encoded string, so verifying a hash
        // proves nothing about which parameters produced it. Reading them off the string
        // is what catches a hash length written where a salt length belongs.
        let credentials = Credentials::new(Argon2Params {
            time_cost: 2,
            memory_cost: 8192,
            parallelism: 1,
            hash_length: 24,
            salt_length: 20,
        });
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

        // The same password hashes differently every time, because the salt is fresh.
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
    fn an_email_normalizes_by_lowercasing_or_is_refused() {
        assert_eq!(
            normalize_email("Ada@Example.COM").as_deref(),
            Some("ada@example.com")
        );
        assert_eq!(
            normalize_email("a.b+tag@Gmail.com").as_deref(),
            Some("a.b+tag@gmail.com")
        );
        assert_eq!(
            normalize_email("linus@kernel.example.com").as_deref(),
            Some("linus@kernel.example.com")
        );

        // Everything outside the subset delegates rather than being guessed at.
        for refused in [
            "",
            "nobody",
            "@example.com",
            "a@",
            "a@localhost",
            // A domain ending in a reserved name receives no mail, whatever precedes it.
            "a@example.invalid",
            "a@host.local",
            "a@site.ONION",
            "a@example",
            "a@-example.com",
            "a@example-.com",
            "a@example..com",
            "a@example.c",
            "a@example.c0m",
            ".a@example.com",
            "a.@example.com",
            "a..b@example.com",
            "\"quoted local\"@example.com",
            "user@über.de",
            // A punycode domain decodes back to Unicode rather than staying as written.
            "a@xn--80ak6aa92e.com",
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
        assert!(credentials.apply(EntityTable::Variables, &mut values));
        assert_eq!(values, before);

        let mut user =
            object(r#"{"username": "ada", "email": "Ada@Example.com", "password": "pw"}"#);
        assert!(credentials.apply(EntityTable::Users, &mut user));
        assert_eq!(user["email"], Value::String("ada@example.com".into()));
        assert!(is_password_hash(user["password"].as_str().unwrap()));

        // An address outside the subset refuses the whole write.
        let mut user = object(r#"{"username": "ada", "email": "a@localhost", "password": "pw"}"#);
        assert!(!credentials.apply(EntityTable::Users, &mut user));

        // So does a column holding something other than text.
        let mut user = object(r#"{"username": "ada", "email": 5, "password": "pw"}"#);
        assert!(!credentials.apply(EntityTable::Users, &mut user));
    }
}
