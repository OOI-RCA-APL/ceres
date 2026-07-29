//! Configuration validation errors.

use std::fmt;

/// A single validation problem, located by a dotted path into the configuration.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Problem {
    pub location: String,
    pub message: String,
}

impl Problem {
    pub fn new(location: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            location: location.into(),
            message: message.into(),
        }
    }

    /// Return the problem with its location nested under a parent section.
    pub fn under(mut self, parent: &str) -> Self {
        if self.location.is_empty() {
            self.location = parent.to_string();
        } else {
            self.location = format!("{parent}.{}", self.location);
        }

        self
    }
}

impl fmt::Display for Problem {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.location.is_empty() {
            write!(formatter, "{}", self.message)
        } else {
            write!(formatter, "{}: {}", self.location, self.message)
        }
    }
}

/// Every validation problem found in one pass over a configuration.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Problems(pub Vec<Problem>);

impl Problems {
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn push(&mut self, problem: Problem) {
        self.0.push(problem);
    }

    /// Absorb another set of problems, nesting each location under a parent section.
    pub fn absorb(&mut self, other: Problems, parent: &str) {
        for problem in other.0 {
            self.0.push(problem.under(parent));
        }
    }

    /// Return `Ok(value)` when no problems were found, and the problems otherwise.
    pub fn into_result<T>(self, value: T) -> Result<T, Problems> {
        if self.is_empty() {
            Ok(value)
        } else {
            Err(self)
        }
    }
}

impl fmt::Display for Problems {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let lines: Vec<String> = self
            .0
            .iter()
            .map(|problem| format!("- {problem}"))
            .collect();
        write!(formatter, "{}", lines.join("\n"))
    }
}

impl std::error::Error for Problems {}
