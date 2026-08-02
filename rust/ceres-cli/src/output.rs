//! Terminal output helpers.
//!
//! Human-readable messages and tables go to stderr, structured results go to stdout. Color
//! resolves from the explicit flag first, then the `NO_COLOR` and `FORCE_COLOR` environment
//! variables, then whether stderr is a terminal.
//!
//! A dump answers the same question against standard output instead, where its own rows
//! are going, so the two resolve separately. See `commands::dump::colored`.

use std::io::{IsTerminal, Write as _};

/// Resolved output settings shared by every command.
#[derive(Debug, Clone, Copy)]
pub struct Output {
    color: bool,
}

impl Output {
    /// Resolve output settings from the command line color override.
    pub fn new(color: Option<bool>) -> Self {
        let color = color
            .or_else(color_from_environment)
            .unwrap_or_else(|| std::io::stderr().is_terminal());

        Self { color }
    }

    /// Write a human-readable line to stderr.
    pub fn write(&self, message: impl AsRef<str>) {
        let mut stderr = std::io::stderr().lock();
        let _ = writeln!(stderr, "{}", message.as_ref());
    }

    /// Write a structured result line to stdout.
    pub fn put(&self, value: impl AsRef<str>) {
        let mut stdout = std::io::stdout().lock();
        let _ = writeln!(stdout, "{}", value.as_ref());
    }

    /// Render a table to stderr with a rounded box.
    pub fn write_table(&self, table: &Table) {
        self.write(table.render(self.color));
    }
}

/// Read the `NO_COLOR` and `FORCE_COLOR` environment variables, `NO_COLOR` winning.
fn color_from_environment() -> Option<bool> {
    if std::env::var_os("NO_COLOR").is_some() {
        return Some(false);
    }

    if std::env::var_os("FORCE_COLOR").is_some() {
        return Some(true);
    }

    None
}

/// One cell's text, and the color it takes when the table is drawn in color.
///
/// The color travels beside the text rather than wrapped around it, because a column is
/// only as wide as its widest cell and an escape sequence has no width. Padding happens
/// first and the color goes on after, so a colored table lines up with an uncolored one.
#[derive(Debug, Default)]
pub struct Cell {
    text: String,
    style: Option<&'static str>,
}

impl Cell {
    /// A cell drawn in the given color.
    pub fn styled(text: String, style: Option<&'static str>) -> Self {
        Self { text, style }
    }
}

impl From<String> for Cell {
    fn from(text: String) -> Self {
        Self { text, style: None }
    }
}

/// A simple table with a header row, rendered with rounded box-drawing characters.
#[derive(Debug, Default)]
pub struct Table {
    title: Option<String>,
    columns: Vec<String>,
    rows: Vec<Vec<Cell>>,
}

impl Table {
    pub fn new(title: Option<&str>) -> Self {
        Self {
            title: title.map(str::to_string),
            ..Self::default()
        }
    }

    pub fn column(&mut self, name: impl Into<String>) -> &mut Self {
        self.columns.push(name.into());
        self
    }

    pub fn row(&mut self, cells: impl IntoIterator<Item = impl Into<Cell>>) -> &mut Self {
        self.rows.push(cells.into_iter().map(Into::into).collect());
        self
    }

    /// Render the table as a string, without a trailing newline.
    pub fn render(&self, color: bool) -> String {
        let mut widths: Vec<usize> = self
            .columns
            .iter()
            .map(|name| name.chars().count())
            .collect();
        for row in &self.rows {
            for (index, cell) in row.iter().enumerate() {
                if let Some(width) = widths.get_mut(index) {
                    *width = (*width).max(cell.text.chars().count());
                }
            }
        }

        let mut lines = Vec::new();
        if let Some(title) = &self.title {
            lines.push(title.clone());
        }

        lines.push(border(&widths, '╭', '┬', '╮'));

        let header = self
            .columns
            .iter()
            .enumerate()
            .map(|(index, name)| {
                let padded = pad(name, widths[index]);
                painted(padded, color.then_some(crate::highlight::HEADING))
            })
            .collect::<Vec<_>>()
            .join(" │ ");
        lines.push(format!("│ {header} │"));
        lines.push(border(&widths, '├', '┼', '┤'));

        for row in &self.rows {
            let cells = widths
                .iter()
                .enumerate()
                .map(|(index, width)| {
                    let cell = row.get(index);
                    let padded = pad(cell.map_or("", |cell| cell.text.as_str()), *width);
                    painted(
                        padded,
                        color.then(|| cell.and_then(|cell| cell.style)).flatten(),
                    )
                })
                .collect::<Vec<_>>()
                .join(" │ ");
            lines.push(format!("│ {cells} │"));
        }

        lines.push(border(&widths, '╰', '┴', '╯'));
        lines.join("\n")
    }
}

/// Build a horizontal border line from the given corner and junction characters.
fn border(widths: &[usize], left: char, junction: char, right: char) -> String {
    let middle = widths
        .iter()
        .map(|width| "─".repeat(width + 2))
        .collect::<Vec<_>>()
        .join(&junction.to_string());

    format!("{left}{middle}{right}")
}

/// Pad a cell value with spaces to the given display width.
fn pad(value: &str, width: usize) -> String {
    let length = value.chars().count();
    format!("{value}{}", " ".repeat(width.saturating_sub(length)))
}

/// Wrap an already-padded cell in its color, if it has one.
///
/// The padding is inside the color rather than outside it, so a cell's background carries
/// through its whole width on a terminal that draws one.
fn painted(padded: String, style: Option<&'static str>) -> String {
    match style {
        Some(style) => format!("{style}{padded}{}", crate::highlight::RESET),
        None => padded,
    }
}

/// Convert a boolean to "Yes" or "No".
pub fn strbool(value: bool) -> &'static str {
    if value { "Yes" } else { "No" }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tables_render_with_rounded_borders() {
        let mut table = Table::new(Some("Engine"));
        table.column("Name").column("Running");
        table.row(["sensor".to_string(), "Yes".to_string()]);

        let rendered = table.render(false);
        let expected = "\
Engine
╭────────┬─────────╮
│ Name   │ Running │
├────────┼─────────┤
│ sensor │ Yes     │
╰────────┴─────────╯";
        assert_eq!(rendered, expected);
    }

    #[test]
    fn a_colored_table_lines_up_with_an_uncolored_one() {
        let build = || {
            let mut table = Table::new(None);
            table.column("Name").column("Count");
            table.row([
                Cell::styled("sensor".to_string(), Some("\x1b[32m")),
                Cell::styled("5".to_string(), Some("\x1b[36m")),
            ]);
            table.row([Cell::from("a longer name".to_string()), Cell::default()]);
            table
        };

        // An escape sequence has no width, so a cell is padded first and colored after.
        // Taking the color back off has to leave the box it would have drawn uncolored.
        let colored = build().render(true);
        let bare = build().render(false);
        assert_ne!(colored, bare);

        let stripped: String = {
            let mut out = String::new();
            let mut rest = colored.as_str();
            while let Some(start) = rest.find('\x1b') {
                out.push_str(&rest[..start]);
                let end = rest[start..].find('m').expect("an escape ends in m");
                rest = &rest[start + end + 1..];
            }

            out.push_str(rest);
            out
        };
        assert_eq!(stripped, bare);
    }
}
