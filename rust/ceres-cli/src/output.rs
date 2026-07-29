//! Terminal output helpers.
//!
//! Human-readable messages and tables go to stderr, structured results go to stdout. Color
//! resolves from the explicit flag first, then the `NO_COLOR` and `FORCE_COLOR` environment
//! variables, then whether stderr is a terminal.

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

/// A simple table with a header row, rendered with rounded box-drawing characters.
#[derive(Debug, Default)]
pub struct Table {
    title: Option<String>,
    columns: Vec<String>,
    rows: Vec<Vec<String>>,
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

    pub fn row(&mut self, cells: impl IntoIterator<Item = String>) -> &mut Self {
        self.rows.push(cells.into_iter().collect());
        self
    }

    /// Render the table as a string, without a trailing newline.
    fn render(&self, color: bool) -> String {
        let mut widths: Vec<usize> = self
            .columns
            .iter()
            .map(|name| name.chars().count())
            .collect();
        for row in &self.rows {
            for (index, cell) in row.iter().enumerate() {
                if let Some(width) = widths.get_mut(index) {
                    *width = (*width).max(cell.chars().count());
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
                if color {
                    format!("\x1b[1m{padded}\x1b[0m")
                } else {
                    padded
                }
            })
            .collect::<Vec<_>>()
            .join(" │ ");
        lines.push(format!("│ {header} │"));
        lines.push(border(&widths, '├', '┼', '┤'));

        for row in &self.rows {
            let cells = widths
                .iter()
                .enumerate()
                .map(|(index, width)| pad(row.get(index).map_or("", String::as_str), *width))
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
}
