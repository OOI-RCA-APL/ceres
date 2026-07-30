//! The native record filter subset.
//!
//! A filter parses from the same query pairs the Python filter models validate, but
//! only for the constructs this module proves it can compile identically. Anything
//! else, an unknown key, an unparseable value, or a construct outside the subset,
//! answers `None`, and the caller delegates the whole request to the Python operation,
//! which either serves it or produces the canonical validation error. The native path
//! therefore never invents an error a client sees.
//!
//! The admissible keys are not written out anywhere. Each entity's `Filterable` derive
//! reads its struct at compile time, and every field's family brings its operators, a
//! timestamp brings the window operators, a level brings ordered bounds, text and enum
//! fields bring equality. Compilation mirrors the Python query layer's `_get_where`
//! semantics, and the cross-backend parity suite holds the two compilers to identical
//! result sets.

use ceres_entities::{FieldFamily, FilterField, FilterValues, Level};
use chrono::{Duration, NaiveDateTime, SubsecRound, Utc};
use sea_query::{Alias, Asterisk, Expr, Order, Query, SelectStatement, SimpleExpr, Value};
use uuid::Uuid;

use crate::records::RecordTable;
use crate::store::Parameter;

/// How values render into the statement, per backend family.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum SqlDialect {
    /// SQLite and Turso, where timestamps and UUIDs compare as their stored text.
    SqliteText,
    Postgres,
}

/// What one wire key means for a table, resolved from the entity's field families.
enum KeyRole {
    /// Equality on a field, one value compiling to `=` and several to `IN`.
    Equality(&'static FilterField),
    /// One of the window operators a timestamp field brings.
    Window(WindowOp),
    /// One of the ordered bounds a level field brings.
    Bound(BoundOp),
    Order,
    Limit,
    Offset,
}

#[derive(Clone, Copy, PartialEq)]
enum WindowOp {
    After,
    Before,
    Timespan,
    MaxAge,
    MinAge,
}

#[derive(Clone, Copy, PartialEq)]
enum BoundOp {
    Minimum,
    Maximum,
}

/// The values one field's equality holds, in the family's typed form.
#[derive(Clone, Debug, PartialEq)]
enum Values {
    Uuids(Vec<Uuid>),
    Texts(Vec<String>),
    Stamps(Vec<NaiveDateTime>),
}

/// One ordering term, a field and its direction.
#[derive(Clone, Copy, Debug, PartialEq)]
struct OrderTerm {
    field: &'static FilterField,
    ascending: bool,
}

/// The parsed subset of one record filter.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecordFilter {
    /// Equality values by wire key, compiled in the entity's field order.
    equalities: Vec<(&'static str, Values)>,
    after: Option<NaiveDateTime>,
    before: Option<NaiveDateTime>,
    timespan: Option<Duration>,
    max_age: Option<Duration>,
    min_age: Option<Duration>,
    /// Level bounds as indexes into the level family's ordered values.
    min_level: Option<usize>,
    max_level: Option<usize>,
    order: Vec<OrderTerm>,
    limit: Option<u64>,
    offset: Option<u64>,
}

impl RecordFilter {
    /// The field and query filter keys the native subset serves for a table.
    ///
    /// Generated from the entity's field families, never written out. Equality for
    /// every native family, the window operators a timestamp brings, the ordered
    /// bounds a level brings, and the query keys.
    pub fn supported_keys(table: RecordTable) -> Vec<&'static str> {
        let mut keys = Vec::new();
        for field in table.fields() {
            if !field.family.native() {
                continue;
            }

            keys.push(field.key);
            match field.family {
                FieldFamily::Timestamp => {
                    keys.extend(["after", "before", "timespan", "max_age", "min_age"]);
                }
                FieldFamily::Level => {
                    keys.extend(bound_keys(field));
                }
                _ => {}
            }
        }

        keys.extend(["order", "limit", "offset"]);
        keys
    }

    /// The filter keys the subset knowingly delegates for a table.
    ///
    /// The field operation filters and the byte and JSON field filters generate from
    /// the entity like the native surface does. What remains is Python's structural
    /// query filters, shared by every table, plus its Python-only constructs, and the
    /// classification test holds the union of both lists to exactly what the Pydantic
    /// models declare so a new filter field cannot ship unclassified.
    pub fn delegated_keys(table: RecordTable) -> Vec<&'static str> {
        const STRUCTURAL: [&str; 10] = [
            "root",
            "or",
            "and",
            "subsample_every",
            "subsample",
            "subsample_select",
            "after_hour",
            "before_hour",
            "after_minute",
            "before_minute",
        ];

        let mut keys: Vec<&'static str> = STRUCTURAL.to_vec();
        for field in table.fields() {
            keys.extend(field.operations);
        }

        // A particle's `class` filters by a Python type, which has no native form.
        if table == RecordTable::Particles {
            keys.push("class");
        }

        keys
    }

    /// Parse query pairs into the subset, `None` when the request must delegate.
    ///
    /// Repeated keys collect into lists, matching how the Python layer folds ordered
    /// pairs before validating.
    pub fn parse(table: RecordTable, pairs: &[(String, String)]) -> Option<Self> {
        let mut filter = Self::default();
        for (key, value) in pairs {
            match resolve(table, key)? {
                KeyRole::Equality(field) => filter.push_equality(field, value)?,
                KeyRole::Window(operator) => match operator {
                    WindowOp::After => set_once(&mut filter.after, parse_timestamp(value)?)?,
                    WindowOp::Before => set_once(&mut filter.before, parse_timestamp(value)?)?,
                    WindowOp::Timespan => {
                        let timespan = parse_duration(value)?;
                        // A timespan is a positive duration on the wire, zero or below
                        // validates as an error there.
                        if timespan < Duration::microseconds(1) {
                            return None;
                        }

                        set_once(&mut filter.timespan, timespan)?;
                    }
                    WindowOp::MaxAge => set_once(&mut filter.max_age, parse_duration(value)?)?,
                    WindowOp::MinAge => set_once(&mut filter.min_age, parse_duration(value)?)?,
                },
                KeyRole::Bound(operator) => {
                    let position = level_position(value)?;
                    match operator {
                        BoundOp::Minimum => set_once(&mut filter.min_level, position)?,
                        BoundOp::Maximum => set_once(&mut filter.max_level, position)?,
                    }
                }
                KeyRole::Order => {
                    let term = parse_order(table, value)?;
                    filter.order.push(term);
                }
                KeyRole::Limit => set_once(&mut filter.limit, value.parse().ok()?)?,
                KeyRole::Offset => set_once(&mut filter.offset, value.parse().ok()?)?,
            }
        }

        Some(filter)
    }

    /// Add one equality value for a field, parsed by its family.
    fn push_equality(&mut self, field: &'static FilterField, value: &str) -> Option<()> {
        let parsed = match field.family {
            FieldFamily::Uuid => Values::Uuids(vec![value.parse().ok()?]),
            // A selector modifier or a relative form is outside the subset. A plain
            // absolute address compiles to the equality the Python selector expression
            // reduces to, and a second one delegates rather than guessing at selector
            // semantics.
            FieldFamily::Address => {
                if !plain_address(value) {
                    return None;
                }

                Values::Texts(vec![value.to_string()])
            }
            FieldFamily::Timestamp => Values::Stamps(vec![parse_timestamp(value)?]),
            FieldFamily::Text => Values::Texts(vec![value.to_string()]),
            FieldFamily::Values(admissible) => {
                if !admissible.contains(&value) {
                    return None;
                }

                Values::Texts(vec![value.to_string()])
            }
            FieldFamily::Level => {
                level_position(value)?;
                Values::Texts(vec![value.to_string()])
            }
            FieldFamily::Bytes | FieldFamily::Json => return None,
        };

        match self
            .equalities
            .iter_mut()
            .find(|(key, _)| *key == field.key)
        {
            None => self.equalities.push((field.key, parsed)),
            Some((_, existing)) => match (existing, parsed) {
                (Values::Uuids(existing), Values::Uuids(more)) => existing.extend(more),
                (Values::Texts(existing), Values::Texts(mut more)) => {
                    if field.family == FieldFamily::Address {
                        return None;
                    }

                    existing.append(&mut more);
                }
                (Values::Stamps(existing), Values::Stamps(more)) => existing.extend(more),
                _ => return None,
            },
        }

        Some(())
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
        for condition in self.conditions(table, dialect) {
            statement.and_where(condition);
        }

        for term in self.order_terms(table) {
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
            for condition in self.conditions(table, dialect) {
                statement.and_where(condition);
            }

            return statement;
        }

        let mut inner = Query::select();
        inner
            .column(Alias::new("id"))
            .from(Alias::new(table.name()));
        for condition in self.conditions(table, dialect) {
            inner.and_where(condition);
        }

        for term in self.order_terms(table) {
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

    /// The `WHERE` conditions, in the entity's field order.
    fn conditions(&self, table: RecordTable, dialect: SqlDialect) -> Vec<SimpleExpr> {
        let mut conditions = Vec::new();
        // `now` truncates to microseconds so arithmetic and rendering match Python's
        // `datetime` resolution exactly.
        let now = Utc::now().naive_utc().trunc_subsecs(6);

        for field in table.fields() {
            let column = Expr::col(Alias::new(field.key));
            if let Some(values) = self.values_of(field) {
                conditions.push(match values {
                    Values::Uuids(ids) => {
                        match_values(column.clone(), ids.iter().map(|id| id_value(*id, dialect)))
                    }
                    Values::Texts(texts) => {
                        match_values(column.clone(), texts.iter().cloned().map(Value::from))
                    }
                    Values::Stamps(stamps) => match_values(
                        column.clone(),
                        stamps.iter().map(|stamp| timestamp_value(*stamp, dialect)),
                    ),
                });
            }

            match field.family {
                FieldFamily::Timestamp => {
                    self.window_conditions(&mut conditions, &column, now, dialect);
                }
                FieldFamily::Level => {
                    let levels = <Level as FilterValues>::VALUES;
                    if let Some(minimum) = self.min_level {
                        let qualifying = levels[minimum..].iter().map(|level| Value::from(*level));
                        conditions.push(column.clone().is_in(qualifying));
                    }

                    if let Some(maximum) = self.max_level {
                        let qualifying = levels[..=maximum].iter().map(|level| Value::from(*level));
                        conditions.push(column.clone().is_in(qualifying));
                    }
                }
                _ => {}
            }
        }

        conditions
    }

    /// The window operator conditions on the timestamp column.
    fn window_conditions(
        &self,
        conditions: &mut Vec<SimpleExpr>,
        column: &Expr,
        now: NaiveDateTime,
        dialect: SqlDialect,
    ) {
        if let Some(after) = self.after {
            conditions.push(column.clone().gte(timestamp_value(after, dialect)));
        }

        if let Some(before) = self.before {
            conditions.push(column.clone().lt(timestamp_value(before, dialect)));
        }

        if let Some(timespan) = self.timespan {
            if let Some(after) = self.after {
                conditions.push(
                    column
                        .clone()
                        .lt(timestamp_value(after + timespan, dialect)),
                );
            } else if let Some(before) = self.before {
                conditions.push(
                    column
                        .clone()
                        .gte(timestamp_value(before - timespan, dialect)),
                );
            } else {
                conditions.push(column.clone().gte(timestamp_value(now - timespan, dialect)));
                conditions.push(column.clone().lt(timestamp_value(now, dialect)));
            }
        }

        if let Some(max_age) = self.max_age {
            conditions.push(column.clone().gt(timestamp_value(now - max_age, dialect)));
        }

        if let Some(min_age) = self.min_age {
            conditions.push(column.clone().lte(timestamp_value(now - min_age, dialect)));
        }
    }

    /// The equality values held for one field.
    fn values_of(&self, field: &FilterField) -> Option<&Values> {
        self.equalities
            .iter()
            .find(|(key, _)| *key == field.key)
            .map(|(_, values)| values)
    }

    /// The order terms, the record default of ascending timestamp when none given.
    fn order_terms(&self, table: RecordTable) -> Vec<OrderTerm> {
        if !self.order.is_empty() {
            return self.order.clone();
        }

        table
            .fields()
            .iter()
            .find(|field| field.family == FieldFamily::Timestamp)
            .map(|field| {
                vec![OrderTerm {
                    field,
                    ascending: true,
                }]
            })
            .unwrap_or_default()
    }
}

/// Resolve what one wire key means for a table, from the entity's field families.
fn resolve(table: RecordTable, key: &str) -> Option<KeyRole> {
    match key {
        "order" => return Some(KeyRole::Order),
        "limit" => return Some(KeyRole::Limit),
        "offset" => return Some(KeyRole::Offset),
        _ => {}
    }

    for field in table.fields() {
        if field.key == key {
            return Some(KeyRole::Equality(field));
        }

        match field.family {
            FieldFamily::Timestamp => {
                let operator = match key {
                    "after" => Some(WindowOp::After),
                    "before" => Some(WindowOp::Before),
                    "timespan" => Some(WindowOp::Timespan),
                    "max_age" => Some(WindowOp::MaxAge),
                    "min_age" => Some(WindowOp::MinAge),
                    _ => None,
                };
                if let Some(operator) = operator {
                    return Some(KeyRole::Window(operator));
                }
            }
            FieldFamily::Level => {
                let [minimum, maximum] = bound_keys(field);
                if key == minimum {
                    return Some(KeyRole::Bound(BoundOp::Minimum));
                }

                if key == maximum {
                    return Some(KeyRole::Bound(BoundOp::Maximum));
                }
            }
            _ => {}
        }
    }

    None
}

/// The bound keys a level field brings, `min_` and `max_` prefixed on its key.
fn bound_keys(field: &FilterField) -> [&'static str; 2] {
    // The record level fields are all named `level` today, and the keys have to be
    // `'static` for the classification lists, so the prefix join is spelled out here
    // and checked against the field at runtime.
    debug_assert_eq!(field.key, "level");
    ["min_level", "max_level"]
}

/// The position of a level name in severity order.
fn level_position(value: &str) -> Option<usize> {
    <Level as FilterValues>::VALUES
        .iter()
        .position(|level| *level == value)
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

/// Parse an order value, `field`, `field:asc`, or `field:desc` over the entity's
/// filterable fields.
fn parse_order(table: RecordTable, text: &str) -> Option<OrderTerm> {
    let (base, ascending) = match text.split_once(':') {
        None => (text, true),
        Some((base, "asc")) => (base, true),
        Some((base, "desc")) => (base, false),
        Some(_) => return None,
    };

    let field = table.fields().iter().find(|field| field.key == base)?;
    if !field.family.native() {
        return None;
    }

    Some(OrderTerm { field, ascending })
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
///
/// Only columns stored as text collate, the way the Python layer's own ordering does.
/// A native UUID or timestamp column takes no collation, PostgreSQL rejects one.
fn order_by(statement: &mut SelectStatement, term: OrderTerm, dialect: SqlDialect) {
    let direction = if term.ascending {
        Order::Asc
    } else {
        Order::Desc
    };

    let text = matches!(
        term.field.family,
        FieldFamily::Address | FieldFamily::Text | FieldFamily::Values(_) | FieldFamily::Level
    );
    if dialect == SqlDialect::Postgres && text {
        let collated = format!("\"{}\" COLLATE \"C\"", term.field.key);
        statement.order_by_expr(Expr::cust(collated), direction);
    } else {
        statement.order_by(Alias::new(term.field.key), direction);
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
            pairs(&[("data", "abc")]),
            pairs(&[("address", "@a,@b")]),
            pairs(&[("address", "@a:children")]),
            pairs(&[("address", "sensor")]),
            pairs(&[("address", "@a"), ("address", "@b")]),
            pairs(&[("after", "not-a-time")]),
            pairs(&[("timespan", "PT5S")]),
            pairs(&[("direction", "sideways")]),
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
    fn supported_keys_generate_from_the_entity_fields() {
        let keys = RecordFilter::supported_keys(RecordTable::Messages);
        for expected in [
            "id",
            "address",
            "timestamp",
            "after",
            "timespan",
            "connection",
            "direction",
            "order",
            "limit",
        ] {
            assert!(keys.contains(&expected), "{expected} missing");
        }

        // Bytes and JSON payloads never derive a native filter.
        assert!(!keys.contains(&"data"));
        assert!(RecordFilter::supported_keys(RecordTable::Logs).contains(&"min_level"));
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
    fn uuid_columns_never_collate_on_postgres() {
        let by_id = RecordFilter::parse(RecordTable::Logs, &pairs(&[("order", "id")])).unwrap();
        let sql = by_id
            .statement(RecordTable::Logs, SqlDialect::Postgres)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(sql.contains("ORDER BY \"id\" ASC"), "{sql}");

        let by_content =
            RecordFilter::parse(RecordTable::Logs, &pairs(&[("order", "content:desc")])).unwrap();
        let sql = by_content
            .statement(RecordTable::Logs, SqlDialect::Postgres)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(
            sql.contains("ORDER BY \"content\" COLLATE \"C\" DESC"),
            "{sql}"
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
            let delegated = RecordFilter::delegated_keys(table);
            for key in RecordFilter::supported_keys(table) {
                assert!(!delegated.contains(&key), "{key} is classified twice");
            }
        }
    }
}
