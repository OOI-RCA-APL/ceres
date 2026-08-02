//! Color for output a person is reading at a terminal.
//!
//! A dump is mostly identifiers, timestamps, and numbers, and telling them apart at a
//! glance is what color is for here. The type a value has is read from the value rather
//! than guessed from its text, so a number is colored as a number because it is one, and
//! the two strings worth recognizing, a UUID and an instant, are recognized by handing
//! them to the parsers that already own those formats.
//!
//! Nothing in here decides whether to color. That is settled once, where the destination
//! is known, and arrives as a flag.

use serde_json::Value;

/// The escape that ends a run of color.
pub const RESET: &str = "\x1b[0m";

/// Bold, which a table's header row takes.
pub const HEADING: &str = "\x1b[1m";

/// Blue and bold, for the name a value is stored under.
const KEY: &str = "\x1b[1;34m";

const NUMBER: &str = "\x1b[36m";
const STRING: &str = "\x1b[32m";
const TRUE: &str = "\x1b[92m";
const FALSE: &str = "\x1b[91m";
const NULL: &str = "\x1b[35m";
const UUID: &str = "\x1b[93m";
const INSTANT: &str = "\x1b[94m";

/// The color a value takes, `None` for one drawn in the terminal's own foreground.
///
/// A table cell holds a value's text without its quotes, so this is the half of the
/// painting that both shapes share.
pub fn style(value: &Value) -> Option<&'static str> {
    Some(match value {
        Value::Null => NULL,
        Value::Bool(true) => TRUE,
        Value::Bool(false) => FALSE,
        Value::Number(_) => NUMBER,
        Value::String(text) => text_style(text),
        // A nested array or object reaching a table cell is drawn as its JSON, which is
        // several types at once and so takes the terminal's own color.
        Value::Array(_) | Value::Object(_) => return None,
    })
}

/// The color one string takes, which is what it holds rather than that it is a string.
///
/// Both formats are recognized by parsing rather than by matching their shape, because a
/// UUID has four accepted spellings and an instant has offsets and fractional seconds.
/// The parsers that own those rules are already here.
fn text_style(text: &str) -> &'static str {
    if uuid::Uuid::parse_str(text).is_ok() {
        UUID
    } else if chrono::DateTime::parse_from_rfc3339(text).is_ok() {
        INSTANT
    } else {
        STRING
    }
}

/// Paint a chunk of JSON lines.
///
/// Each line is parsed to be painted, which is a second pass over rows this process just
/// wrote. It costs one parse per row, and it only ever runs when someone at a terminal
/// asked for JSON rather than the table they would have been given by default, so the
/// rows are as many as a person is going to read.
///
/// A line that will not parse is passed through as it is. There should not be one, and a
/// dump that starts eating its own output would be a worse failure than an uncolored line.
pub fn painted(bytes: Vec<u8>) -> Vec<u8> {
    let Ok(text) = std::str::from_utf8(&bytes) else {
        return bytes;
    };

    let mut out = String::with_capacity(text.len() * 2);
    for line in text.split_inclusive('\n') {
        let trimmed = line.trim_end_matches(['\n', '\r']);
        match serde_json::from_str::<Value>(trimmed) {
            Ok(value) => {
                paint(&value, &mut out);
                out.push_str(&line[trimmed.len()..]);
            }
            Err(_) => out.push_str(line),
        }
    }

    out.into_bytes()
}

/// Write one value as colored JSON.
fn paint(value: &Value, out: &mut String) {
    match value {
        Value::Null => run(out, NULL, "null"),
        Value::Bool(true) => run(out, TRUE, "true"),
        Value::Bool(false) => run(out, FALSE, "false"),
        Value::Number(number) => run(out, NUMBER, &number.to_string()),
        Value::String(text) => run(out, text_style(text), &quoted(text)),
        Value::Array(items) => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }

                paint(item, out);
            }

            out.push(']');
        }
        Value::Object(fields) => {
            out.push('{');
            for (index, (name, held)) in fields.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }

                run(out, KEY, &quoted(name));
                out.push(':');
                paint(held, out);
            }

            out.push('}');
        }
    }
}

/// Write one string the way JSON would have written it, quotes and escapes included.
///
/// Escaping here is what keeps a value from painting itself. A record's payload is
/// arbitrary instrument bytes carried as text, so a value can hold an escape byte, and
/// leaving one unescaped would let a stored value recolor the screen it is printed on.
fn quoted(text: &str) -> String {
    serde_json::to_string(text).unwrap_or_else(|_| format!("{text:?}"))
}

/// Write one run of text in one color.
fn run(out: &mut String, style: &str, text: &str) {
    out.push_str(style);
    out.push_str(text);
    out.push_str(RESET);
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The text a painted run carries, with the escapes taken back off.
    fn plain(painted: &str) -> String {
        let mut out = String::new();
        let mut rest = painted;
        while let Some(start) = rest.find('\x1b') {
            out.push_str(&rest[..start]);
            let end = rest[start..]
                .find('m')
                .expect("every escape written here ends in m");
            rest = &rest[start + end + 1..];
        }

        out.push_str(rest);
        out
    }

    #[test]
    fn a_value_is_colored_by_what_it_is() {
        let uuid = Value::String("0195f0b4-3c6a-7c00-8000-000000000000".to_string());
        let instant = Value::String("2026-07-30T12:00:00Z".to_string());

        assert_eq!(style(&Value::from(5)), Some(NUMBER));
        assert_eq!(style(&Value::Null), Some(NULL));
        assert_eq!(style(&Value::Bool(true)), Some(TRUE));
        assert_eq!(style(&Value::Bool(false)), Some(FALSE));
        assert_eq!(style(&Value::String("drive".to_string())), Some(STRING));
        assert_eq!(style(&uuid), Some(UUID));
        assert_eq!(style(&instant), Some(INSTANT));

        // A value that is several types at once has no one color to take.
        assert_eq!(style(&Value::Array(vec![Value::from(1)])), None);
    }

    #[test]
    fn painting_leaves_the_json_it_painted() {
        // Color is added around the text rather than instead of it, so a painted line
        // still parses as the line it was.
        let line = br#"{"name":"speed","value":5,"gone":null}"#.to_vec();
        let painted = painted(line.clone());
        assert_ne!(painted, line);
        assert_eq!(
            plain(&String::from_utf8(painted).expect("painting writes text")).as_bytes(),
            line
        );
    }

    #[test]
    fn every_line_of_a_chunk_is_painted_and_keeps_its_breaks() {
        let chunk = painted(b"{\"a\":1}\n{\"b\":2}\n".to_vec());
        let chunk = String::from_utf8(chunk).expect("painting writes text");

        assert_eq!(plain(&chunk), "{\"a\":1}\n{\"b\":2}\n");
        assert_eq!(chunk.lines().count(), 2);
    }

    #[test]
    fn a_line_that_is_not_json_goes_out_as_it_is() {
        // A dump that started eating its own output would be a worse failure than an
        // uncolored line.
        assert_eq!(painted(b"not json\n".to_vec()), b"not json\n");
    }

    #[test]
    fn a_stored_escape_cannot_paint_the_screen_it_prints_on() {
        // The escape arrives spelled the way JSON spells one, because a raw control
        // character is not something a JSON string may hold in the first place.
        let spelled = serde_json::to_string("\u{1b}[31mred").expect("a string always writes");
        let chunk = painted(format!("{{\"data\":{spelled}}}").into_bytes());
        let chunk = String::from_utf8(chunk).expect("painting writes text");

        // It goes out spelled the same way, so a value read out of a record cannot
        // recolor the screen it prints on.
        assert!(chunk.contains(&spelled), "{chunk}");
        assert!(!chunk.contains("\u{1b}[31m"), "{chunk}");
    }
}
