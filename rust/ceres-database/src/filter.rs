//! The native record filter subset.
//!
//! A filter parses from the same query pairs the Python filter models validate, but
//! only for the constructs this module proves it can compile identically. Anything
//! else, an unknown key, an unparseable value, or a construct outside the subset,
//! answers `None`, and the caller delegates the whole request to the Python operation,
//! which either serves it or produces the canonical validation error. The native path
//! therefore never invents an error a client sees.
//!
//! Compilation mirrors the Python query layer's `_get_where` semantics construct for
//! construct, and the cross-backend parity suite holds the two compilers to identical
//! result sets.

use chrono::{Duration, NaiveDateTime, SubsecRound, Utc};
use sea_query::{Alias, Asterisk, Expr, Order, Query, SelectStatement, SimpleExpr, Value};
use uuid::Uuid;

use crate::records::RecordTable;
use crate::store::Parameter;

/// Every level, in severity order, for expanding `min_level`/`max_level` into `IN`
/// lists the way the Python filter does.
const LEVELS: [&str; 5] = ["debug", "info", "warning", "error", "critical"];

/// The columns an order value may name, shared across the record tables.
const COMMON_ORDER: [&str; 3] = ["id", "address", "timestamp"];

/// Text columns, which order with an explicit `C` collation on PostgreSQL so the order
/// is a property of Ceres rather than of the cluster's locale.
const TEXT_COLUMNS: [&str; 6] = ["id", "address", "connection", "direction", "type", "level"];

/// How values render into the statement, per backend family.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum SqlDialect {
    /// SQLite and Turso, where timestamps and UUIDs compare as their stored text.
    SqliteText,
    Postgres,
}

/// One ordering term, a column and its direction.
#[derive(Clone, Debug, PartialEq)]
struct OrderTerm {
    column: &'static str,
    ascending: bool,
}

/// The parsed subset of one record filter.
///
/// Fields hold lists where the wire accepts one value or several, an empty list
/// meaning the key was absent.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecordFilter {
    id: Vec<Uuid>,
    address: Option<String>,
    timestamp: Vec<NaiveDateTime>,
    after: Option<NaiveDateTime>,
    before: Option<NaiveDateTime>,
    timespan: Option<Duration>,
    max_age: Option<Duration>,
    min_age: Option<Duration>,
    order: Vec<OrderTerm>,
    limit: Option<u64>,
    offset: Option<u64>,
    /// `connection` equality on messages.
    connection: Vec<String>,
    /// `direction` equality on messages, as the stored text.
    direction: Vec<String>,
    /// `type` equality on particles and alerts.
    kind: Vec<String>,
    /// `level` equality on alerts and logs, as the stored text.
    level: Vec<String>,
    min_level: Option<&'static str>,
    max_level: Option<&'static str>,
    /// `content` equality on logs.
    content: Vec<String>,
}

impl RecordFilter {
    /// The query keys the native subset serves for a table, underscore wire names.
    pub fn supported_keys(table: RecordTable) -> &'static [&'static str] {
        macro_rules! keys {
            ($($extra:literal),*) => {
                &[
                    "id", "address", "timestamp", "after", "before", "timespan", "max_age",
                    "min_age", "order", "limit", "offset", $($extra),*
                ]
            };
        }

        match table {
            RecordTable::Messages => keys!("connection", "direction"),
            RecordTable::Particles => keys!("type"),
            RecordTable::Alerts => keys!("type", "level", "min_level", "max_level"),
            RecordTable::Logs => keys!("level", "min_level", "max_level", "content"),
        }
    }

    /// The query keys the subset knowingly delegates for a table.
    ///
    /// Together with [`Self::supported_keys`], this covers every field the Python
    /// filter declares, and the classification test holds the union to that shape so a
    /// new filter field cannot ship unclassified.
    pub fn delegated_keys(table: RecordTable) -> &'static [&'static str] {
        macro_rules! keys {
            ($($extra:literal),*) => {
                &[
                    "root", "or", "and", "subsample_every", "subsample", "subsample_select",
                    "after_hour", "before_hour", "after_minute", "before_minute", $($extra),*
                ]
            };
        }

        match table {
            RecordTable::Messages => keys!(
                "connection_contains",
                "connection_prefix",
                "connection_suffix",
                "data",
                "contains",
                "prefix",
                "suffix"
            ),
            RecordTable::Particles => keys!(
                "class",
                "type_contains",
                "type_prefix",
                "type_suffix",
                "data_contains",
                "data_prefix",
                "data_suffix"
            ),
            RecordTable::Alerts => keys!(
                "type_contains",
                "type_prefix",
                "type_suffix",
                "data_contains",
                "data_prefix",
                "data_suffix"
            ),
            RecordTable::Logs => keys!("contains", "prefix", "suffix"),
        }
    }

    /// Parse query pairs into the subset, `None` when the request must delegate.
    ///
    /// Repeated keys collect into lists, matching how the Python layer folds ordered
    /// pairs before validating.
    pub fn parse(table: RecordTable, pairs: &[(String, String)]) -> Option<Self> {
        let supported = Self::supported_keys(table);

        let mut filter = Self::default();
        for (key, value) in pairs {
            if !supported.contains(&key.as_str()) {
                return None;
            }

            match key.as_str() {
                "id" => filter.id.push(value.parse().ok()?),
                "address" => {
                    // A second address, a selector modifier, or a relative form is
                    // outside the subset. A plain absolute address compiles to the
                    // equality the Python selector expression reduces to.
                    if filter.address.is_some() || !plain_address(value) {
                        return None;
                    }

                    filter.address = Some(value.clone());
                }
                "timestamp" => filter.timestamp.push(parse_timestamp(value)?),
                "after" => set_once(&mut filter.after, parse_timestamp(value)?)?,
                "before" => set_once(&mut filter.before, parse_timestamp(value)?)?,
                "timespan" => set_once(&mut filter.timespan, parse_duration(value)?)?,
                "max_age" => set_once(&mut filter.max_age, parse_duration(value)?)?,
                "min_age" => set_once(&mut filter.min_age, parse_duration(value)?)?,
                "order" => filter.order.push(parse_order(table, value)?),
                "limit" => set_once(&mut filter.limit, value.parse().ok()?)?,
                "offset" => set_once(&mut filter.offset, value.parse().ok()?)?,
                "connection" => filter.connection.push(value.clone()),
                "direction" => {
                    if value != "send" && value != "receive" {
                        return None;
                    }

                    filter.direction.push(value.clone());
                }
                "type" => filter.kind.push(value.clone()),
                "level" => filter.level.push(parse_level(value)?.to_string()),
                "min_level" => set_once(&mut filter.min_level, parse_level(value)?)?,
                "max_level" => set_once(&mut filter.max_level, parse_level(value)?)?,
                "content" => filter.content.push(value.clone()),
                _ => return None,
            }
        }

        if filter.timespan.is_some() && filter.timespan < Some(Duration::microseconds(1)) {
            // `timespan` is a positive duration on the wire, zero or below validates
            // as an error there.
            return None;
        }

        Some(filter)
    }

    /// The parsed limit, which callers cap before executing on the server.
    pub fn limit(&self) -> Option<u64> {
        self.limit
    }

    /// Cap the limit, defaulting an absent one, the way the route's `Limit` wrapper
    /// does. A limit above the cap is a validation error, so it delegates.
    pub fn with_limit_cap(mut self, cap: u64) -> Option<Self> {
        match self.limit {
            None => self.limit = Some(cap),
            Some(limit) if limit > cap => return None,
            Some(_) => {}
        }

        Some(self)
    }

    /// Build the listing statement, mirroring the Python layer's `apply`.
    pub fn statement(&self, table: RecordTable, dialect: SqlDialect) -> SelectStatement {
        let mut statement = Query::select();
        statement.column(Asterisk).from(Alias::new(table.name()));
        for condition in self.conditions(dialect) {
            statement.and_where(condition);
        }

        for term in self.order_terms() {
            order_by(&mut statement, term, dialect);
        }

        if let Some(limit) = self.limit {
            statement.limit(limit);
        }

        if let Some(offset) = self.offset {
            statement.offset(offset);
        }

        statement
    }

    /// Build the count statement.
    ///
    /// A limit or offset bounds the count itself, matching the Python layer, which
    /// counts over the paged primary-key subquery in that case.
    pub fn count_statement(&self, table: RecordTable, dialect: SqlDialect) -> SelectStatement {
        if self.limit.is_none() && self.offset.is_none() {
            let mut statement = Query::select();
            statement
                .expr(Expr::cust("COUNT(*)"))
                .from(Alias::new(table.name()));
            for condition in self.conditions(dialect) {
                statement.and_where(condition);
            }

            return statement;
        }

        let mut inner = Query::select();
        inner
            .column(Alias::new("id"))
            .from(Alias::new(table.name()));
        for condition in self.conditions(dialect) {
            inner.and_where(condition);
        }

        for term in self.order_terms() {
            order_by(&mut inner, term, dialect);
        }

        if let Some(limit) = self.limit {
            inner.limit(limit);
        }

        if let Some(offset) = self.offset {
            inner.offset(offset);
        }

        let mut statement = Query::select();
        statement
            .expr(Expr::cust("COUNT(*)"))
            .from_subquery(inner, Alias::new("matched"));
        statement
    }

    /// The `WHERE` conditions, in the order the Python filter yields them.
    fn conditions(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        let mut conditions = Vec::new();
        let column = |name: &str| Expr::col(Alias::new(name));
        // `now` truncates to microseconds so arithmetic and rendering match Python's
        // `datetime` resolution exactly.
        let now = Utc::now().naive_utc().trunc_subsecs(6);

        if !self.id.is_empty() {
            let values = self.id.iter().map(|id| id_value(*id, dialect));
            conditions.push(match_values(column("id"), values));
        }

        if let Some(address) = &self.address {
            conditions.push(column("address").eq(address.clone()));
        }

        if !self.timestamp.is_empty() {
            let values = self
                .timestamp
                .iter()
                .map(|timestamp| timestamp_value(*timestamp, dialect));
            conditions.push(match_values(column("timestamp"), values));
        }

        if let Some(after) = self.after {
            conditions.push(column("timestamp").gte(timestamp_value(after, dialect)));
        }

        if let Some(before) = self.before {
            conditions.push(column("timestamp").lt(timestamp_value(before, dialect)));
        }

        if let Some(timespan) = self.timespan {
            if let Some(after) = self.after {
                conditions.push(column("timestamp").lt(timestamp_value(after + timespan, dialect)));
            } else if let Some(before) = self.before {
                conditions
                    .push(column("timestamp").gte(timestamp_value(before - timespan, dialect)));
            } else {
                conditions.push(column("timestamp").gte(timestamp_value(now - timespan, dialect)));
                conditions.push(column("timestamp").lt(timestamp_value(now, dialect)));
            }
        }

        if let Some(max_age) = self.max_age {
            conditions.push(column("timestamp").gt(timestamp_value(now - max_age, dialect)));
        }

        if let Some(min_age) = self.min_age {
            conditions.push(column("timestamp").lte(timestamp_value(now - min_age, dialect)));
        }

        if !self.connection.is_empty() {
            let values = self.connection.iter().cloned().map(Value::from);
            conditions.push(match_values(column("connection"), values));
        }

        if !self.direction.is_empty() {
            let values = self.direction.iter().cloned().map(Value::from);
            conditions.push(match_values(column("direction"), values));
        }

        if !self.kind.is_empty() {
            let values = self.kind.iter().cloned().map(Value::from);
            conditions.push(match_values(column("type"), values));
        }

        if !self.level.is_empty() {
            let values = self.level.iter().cloned().map(Value::from);
            conditions.push(match_values(column("level"), values));
        }

        if let Some(minimum) = self.min_level {
            let start = LEVELS.iter().position(|level| *level == minimum);
            let qualifying = LEVELS[start.unwrap_or(0)..]
                .iter()
                .map(|level| Value::from(*level));
            conditions.push(column("level").is_in(qualifying));
        }

        if let Some(maximum) = self.max_level {
            let end = LEVELS.iter().position(|level| *level == maximum);
            let qualifying = LEVELS[..=end.unwrap_or(LEVELS.len() - 1)]
                .iter()
                .map(|level| Value::from(*level));
            conditions.push(column("level").is_in(qualifying));
        }

        if !self.content.is_empty() {
            let values = self.content.iter().cloned().map(Value::from);
            conditions.push(match_values(column("content"), values));
        }

        conditions
    }

    /// The order terms, the record default of ascending timestamp when none given.
    fn order_terms(&self) -> Vec<OrderTerm> {
        if self.order.is_empty() {
            return vec![OrderTerm {
                column: "timestamp",
                ascending: true,
            }];
        }

        self.order.clone()
    }
}

/// Refuse a key that appears more than once where the wire takes one value.
fn set_once<T>(slot: &mut Option<T>, value: T) -> Option<()> {
    if slot.is_some() {
        return None;
    }

    *slot = Some(value);
    Some(())
}

/// Whether an address is a plain absolute one the subset compiles to equality.
///
/// Selector features, modifiers (`:`), multiple segments (`,`), wildcards, relative
/// forms, and whitespace, all delegate.
fn plain_address(text: &str) -> bool {
    let Some(rest) = text.strip_prefix('@') else {
        return false;
    };

    !rest.is_empty()
        && rest.chars().all(|character| {
            character.is_ascii_lowercase()
                || character.is_ascii_digit()
                || character == '_'
                || character == '-'
                || character == '.'
        })
        && !rest.starts_with('.')
        && !rest.ends_with('.')
        && !rest.contains("..")
}

/// Parse a wire timestamp, RFC 3339 or a naive form read as UTC, like the Python type.
fn parse_timestamp(text: &str) -> Option<NaiveDateTime> {
    if let Ok(aware) = chrono::DateTime::parse_from_rfc3339(text) {
        return Some(aware.naive_utc());
    }

    for format in ["%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%dT%H:%M:%S%.f"] {
        if let Ok(naive) = NaiveDateTime::parse_from_str(text, format) {
            return Some(naive);
        }
    }

    None
}

/// Parse a wire duration, the suffix grammar or bare seconds. ISO 8601 intervals
/// delegate rather than risking a second implementation of that grammar.
fn parse_duration(text: &str) -> Option<Duration> {
    let text = text.trim().replace(' ', "").to_lowercase();
    let (number, scale) = if let Some(number) = text.strip_suffix("us") {
        (number, 1.0)
    } else if let Some(number) = text.strip_suffix("ms") {
        (number, 1_000.0)
    } else if let Some(number) = text.strip_suffix('s') {
        (number, 1_000_000.0)
    } else if let Some(number) = text.strip_suffix('m') {
        (number, 60.0 * 1_000_000.0)
    } else if let Some(number) = text.strip_suffix('h') {
        (number, 3_600.0 * 1_000_000.0)
    } else if let Some(number) = text.strip_suffix('d') {
        (number, 86_400.0 * 1_000_000.0)
    } else {
        (text.as_str(), 1_000_000.0)
    };

    if number.is_empty() || number.starts_with('p') || number.starts_with('+') {
        return None;
    }

    let value: f64 = number.parse().ok()?;
    if !value.is_finite() || value < 0.0 {
        return None;
    }

    Some(Duration::microseconds((value * scale).round() as i64))
}

/// Parse an order value, `field`, `field:asc`, or `field:desc` over the allowlist.
fn parse_order(table: RecordTable, text: &str) -> Option<OrderTerm> {
    let (base, ascending) = match text.split_once(':') {
        None => (text, true),
        Some((base, "asc")) => (base, true),
        Some((base, "desc")) => (base, false),
        Some(_) => return None,
    };

    let extra: &[&str] = match table {
        RecordTable::Messages => &["connection", "direction"],
        RecordTable::Particles => &["type"],
        RecordTable::Alerts => &["type", "level"],
        RecordTable::Logs => &["level", "content"],
    };
    let column = COMMON_ORDER
        .iter()
        .chain(extra)
        .find(|column| **column == base)?;

    Some(OrderTerm { column, ascending })
}

/// Parse a level name to its canonical form.
fn parse_level(text: &str) -> Option<&'static str> {
    LEVELS.iter().find(|level| **level == text).copied()
}

/// An equality for one value, an `IN` for several, like the Python `_sql_match_value`.
fn match_values(column: Expr, values: impl Iterator<Item = Value> + Clone) -> SimpleExpr {
    let mut peek = values.clone();
    let first = peek.next();
    match (first, peek.next()) {
        (Some(value), None) => column.eq(value),
        _ => column.is_in(values),
    }
}

/// A UUID in its bound form, stored text on the SQLite family.
fn id_value(id: Uuid, dialect: SqlDialect) -> Value {
    match dialect {
        SqlDialect::SqliteText => Value::from(id.to_string()),
        SqlDialect::Postgres => Value::from(id),
    }
}

/// A timestamp in its bound form, the stored text on the SQLite family.
fn timestamp_value(timestamp: NaiveDateTime, dialect: SqlDialect) -> Value {
    match dialect {
        SqlDialect::SqliteText => Value::from(Parameter::timestamp_text(&timestamp)),
        SqlDialect::Postgres => Value::from(timestamp),
    }
}

/// Apply one order term, collating text by code point on PostgreSQL.
fn order_by(statement: &mut SelectStatement, term: OrderTerm, dialect: SqlDialect) {
    let direction = if term.ascending {
        Order::Asc
    } else {
        Order::Desc
    };

    if dialect == SqlDialect::Postgres && TEXT_COLUMNS.contains(&term.column) {
        let collated = format!("\"{}\" COLLATE \"C\"", term.column);
        statement.order_by_expr(Expr::cust(collated), direction);
    } else {
        statement.order_by(Alias::new(term.column), direction);
    }
}

#[cfg(test)]
mod tests {
    use sea_query::SqliteQueryBuilder;

    use super::*;

    fn pairs(entries: &[(&str, &str)]) -> Vec<(String, String)> {
        entries
            .iter()
            .map(|(key, value)| (key.to_string(), value.to_string()))
            .collect()
    }

    #[test]
    fn unknown_keys_and_unsupported_constructs_delegate() {
        for rejected in [
            pairs(&[("nope", "1")]),
            pairs(&[("subsample", "10")]),
            pairs(&[("and", "{}")]),
            pairs(&[("address", "@a,@b")]),
            pairs(&[("address", "@a:children")]),
            pairs(&[("address", "sensor")]),
            pairs(&[("address", "@a"), ("address", "@b")]),
            pairs(&[("after", "not-a-time")]),
            pairs(&[("timespan", "PT5S")]),
            pairs(&[("direction", "sideways")]),
            pairs(&[("level", "loud")]),
            pairs(&[("order", "data")]),
            pairs(&[("order", "timestamp:sideways")]),
            pairs(&[("limit", "-1")]),
            pairs(&[("limit", "5"), ("limit", "6")]),
        ] {
            assert_eq!(
                RecordFilter::parse(RecordTable::Messages, &rejected),
                None,
                "{rejected:?}"
            );
        }
    }

    #[test]
    fn per_table_keys_apply_only_to_their_tables() {
        let connection = pairs(&[("connection", "serial")]);
        assert!(RecordFilter::parse(RecordTable::Messages, &connection).is_some());
        assert!(RecordFilter::parse(RecordTable::Particles, &connection).is_none());

        let level = pairs(&[("min_level", "warning")]);
        assert!(RecordFilter::parse(RecordTable::Alerts, &level).is_some());
        assert!(RecordFilter::parse(RecordTable::Messages, &level).is_none());
    }

    #[test]
    fn statements_compile_the_python_semantics() {
        let filter = RecordFilter::parse(
            RecordTable::Alerts,
            &pairs(&[
                ("address", "@sensor.temp"),
                ("min_level", "warning"),
                ("order", "timestamp:desc"),
                ("limit", "10"),
            ]),
        )
        .unwrap();

        let sql = filter
            .statement(RecordTable::Alerts, SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert_eq!(
            sql,
            "SELECT * FROM \"alerts\" WHERE \"address\" = '@sensor.temp' AND \"level\" IN \
             ('warning', 'error', 'critical') ORDER BY \"timestamp\" DESC LIMIT 10"
        );
    }

    #[test]
    fn single_values_compile_to_equality_and_lists_to_in() {
        let single = RecordFilter::parse(RecordTable::Logs, &pairs(&[("level", "info")])).unwrap();
        let sql = single
            .statement(RecordTable::Logs, SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("\"level\" = 'info'"), "{sql}");

        let several = RecordFilter::parse(
            RecordTable::Logs,
            &pairs(&[("level", "info"), ("level", "error")]),
        )
        .unwrap();
        let sql = several
            .statement(RecordTable::Logs, SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("\"level\" IN ('info', 'error')"), "{sql}");
    }

    #[test]
    fn bounded_counts_page_before_counting() {
        let filter =
            RecordFilter::parse(RecordTable::Particles, &pairs(&[("limit", "5")])).unwrap();
        let sql = filter
            .count_statement(RecordTable::Particles, SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert_eq!(
            sql,
            "SELECT COUNT(*) FROM (SELECT \"id\" FROM \"particles\" ORDER BY \"timestamp\" ASC \
             LIMIT 5) AS \"matched\""
        );
    }

    #[test]
    fn durations_parse_the_suffix_grammar() {
        assert_eq!(parse_duration("5s"), Some(Duration::seconds(5)));
        assert_eq!(parse_duration("1.5 h"), Some(Duration::seconds(5400)));
        assert_eq!(parse_duration("100ms"), Some(Duration::milliseconds(100)));
        assert_eq!(parse_duration("7d"), Some(Duration::days(7)));
        assert_eq!(parse_duration("90"), Some(Duration::seconds(90)));
        assert_eq!(parse_duration("PT5S"), None);
        assert_eq!(parse_duration("-5s"), None);
        assert_eq!(parse_duration("week"), None);
    }

    #[test]
    fn limits_cap_and_default_like_the_route_wrapper() {
        let filter = RecordFilter::parse(RecordTable::Messages, &pairs(&[])).unwrap();
        assert_eq!(filter.with_limit_cap(1000).unwrap().limit(), Some(1000));

        let low = RecordFilter::parse(RecordTable::Messages, &pairs(&[("limit", "5")])).unwrap();
        assert_eq!(low.with_limit_cap(1000).unwrap().limit(), Some(5));

        let high =
            RecordFilter::parse(RecordTable::Messages, &pairs(&[("limit", "5000")])).unwrap();
        assert!(high.with_limit_cap(1000).is_none());
    }

    #[test]
    fn the_key_classification_is_disjoint() {
        for table in [
            RecordTable::Messages,
            RecordTable::Particles,
            RecordTable::Alerts,
            RecordTable::Logs,
        ] {
            for key in RecordFilter::supported_keys(table) {
                assert!(
                    !RecordFilter::delegated_keys(table).contains(key),
                    "{key} is classified twice"
                );
            }
        }
    }
}
