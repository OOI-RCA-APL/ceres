//! The native record filter compiler.
//!
//! A filter parses from the same query pairs the Python filter models validate, into a
//! tree whose root carries the query controls, ordering and pagination, and whose nodes
//! carry the matching conditions. Constructs the compiler does not serve yet refuse
//! with [`Refusal::Delegated`], and the caller hands the whole request to the Python
//! operation, which either serves it or produces the canonical validation error. A
//! value that is wrong on the wire refuses with [`Refusal::Invalid`] instead, which
//! callers treat the same way today, so the native path never invents an error a
//! client sees.
//!
//! The admissible keys are not written out anywhere. Each entity's `Filterable` derive
//! reads its struct at compile time, and every field's family brings its operators, a
//! timestamp brings the window operators, a level brings ordered bounds, text and enum
//! fields bring equality. Compilation mirrors the Python query layer's `_get_where`
//! semantics, and the cross-backend parity suite holds the two compilers to identical
//! result sets.

use ceres_entities::{FieldFamily, FilterField, FilterValues, Level, OperationKind};
use chrono::{Duration, NaiveDateTime, SubsecRound, Utc};
use sea_query::{
    Alias, Asterisk, BinOper, Expr, ExprTrait, Func, LikeExpr, Order, Query, SelectStatement,
    SimpleExpr, Value,
};
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

/// Why a filter refused to parse natively.
///
/// Both variants delegate to the Python operation today. They stay distinct because
/// the two must diverge, a delegated construct is one the compiler will serve once its
/// port lands, while an invalid value stays an error wherever it is parsed.
#[derive(Clone, Debug, PartialEq)]
pub enum Refusal {
    /// The construct sits outside what the compiler serves, so the request delegates.
    Delegated,
    /// The value is wrong in a way the wire reports as a validation error.
    Invalid(String),
}

impl Refusal {
    /// An invalid refusal with its wire message.
    fn invalid(message: impl Into<String>) -> Self {
        Self::Invalid(message.into())
    }
}

/// What one wire key means for a table, resolved from the entity's field families.
enum KeyRole {
    /// Equality on a field, one value compiling to `=` and several to `IN`.
    Equality(&'static FilterField),
    /// One of a field's operation filters, matching within its content.
    Operation(&'static FilterField, OperationKind),
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
    Bytes(Vec<Vec<u8>>),
}

/// One field operation filter, matching within the field's content.
#[derive(Clone, Debug, PartialEq)]
struct OperationFilter {
    field: &'static FilterField,
    kind: OperationKind,
    /// The patterns, text for text and JSON fields and bytes for byte fields.
    values: Values,
}

/// One ordering term, a field and its direction.
#[derive(Clone, Copy, Debug, PartialEq)]
struct OrderTerm {
    field: &'static FilterField,
    ascending: bool,
}

/// One node of the filter tree, the matching conditions of one group.
///
/// The root node holds the filter's own conditions. Boolean `or`/`and` groups will
/// hang their own nodes off it, each compiling to the same condition set over the same
/// fields.
#[derive(Clone, Debug, Default, PartialEq)]
struct FilterNode {
    /// Equality values by wire key, compiled in the entity's field order.
    equalities: Vec<(&'static str, Values)>,
    /// Operation filters, compiled per field in the entity's field order.
    operations: Vec<OperationFilter>,
    after: Option<NaiveDateTime>,
    before: Option<NaiveDateTime>,
    timespan: Option<Duration>,
    max_age: Option<Duration>,
    min_age: Option<Duration>,
    /// Level bounds as indexes into the level family's ordered values.
    min_level: Option<usize>,
    max_level: Option<usize>,
}

/// A parsed record filter, the tree's root plus the query controls.
#[derive(Clone, Debug, PartialEq)]
pub struct RecordFilter {
    table: RecordTable,
    node: FilterNode,
    order: Vec<OrderTerm>,
    limit: Option<u64>,
    offset: Option<u64>,
}

impl RecordFilter {
    /// The field and query filter keys the native compiler serves for a table.
    ///
    /// Generated from the entity's field families, never written out. Equality for
    /// every native family, each field's operation filters, the window operators a
    /// timestamp brings, the ordered bounds a level brings, and the query keys.
    pub fn supported_keys(table: RecordTable) -> Vec<&'static str> {
        let mut keys = Vec::new();
        for field in table.fields() {
            for operation in field.operations {
                keys.push(operation.key);
            }

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

    /// The filter keys the compiler knowingly delegates for a table.
    ///
    /// What remains is Python's structural query filters, shared by every table, plus
    /// its Python-only constructs, and the classification test holds the union of this
    /// list and the supported one to exactly what the Pydantic models declare so a new
    /// filter field cannot ship unclassified.
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

        // A particle's `class` filters by a Python type, which has no native form.
        if table == RecordTable::Particles {
            keys.push("class");
        }

        keys
    }

    /// Parse query pairs into a filter, refusing what cannot compile natively.
    ///
    /// Repeated keys collect into lists, matching how the Python layer folds ordered
    /// pairs before validating.
    pub fn parse(table: RecordTable, pairs: &[(String, String)]) -> Result<Self, Refusal> {
        let mut filter = Self {
            table,
            node: FilterNode::default(),
            order: Vec::new(),
            limit: None,
            offset: None,
        };
        for (key, value) in pairs {
            match resolve(table, key)? {
                KeyRole::Equality(field) => filter.node.push_equality(field, value)?,
                KeyRole::Operation(field, kind) => filter.node.push_operation(field, kind, value),
                KeyRole::Window(operator) => match operator {
                    WindowOp::After => {
                        set_once(&mut filter.node.after, key, parse_timestamp(value)?)?;
                    }
                    WindowOp::Before => {
                        set_once(&mut filter.node.before, key, parse_timestamp(value)?)?;
                    }
                    WindowOp::Timespan => {
                        let timespan = parse_duration(value)?;
                        if timespan < Duration::microseconds(1) {
                            return Err(Refusal::invalid("timespan must be greater than zero"));
                        }

                        set_once(&mut filter.node.timespan, key, timespan)?;
                    }
                    WindowOp::MaxAge => {
                        set_once(&mut filter.node.max_age, key, parse_duration(value)?)?;
                    }
                    WindowOp::MinAge => {
                        set_once(&mut filter.node.min_age, key, parse_duration(value)?)?;
                    }
                },
                KeyRole::Bound(operator) => {
                    let position = level_position(value)
                        .ok_or_else(|| Refusal::invalid(format!("invalid level {value:?}")))?;
                    match operator {
                        BoundOp::Minimum => set_once(&mut filter.node.min_level, key, position)?,
                        BoundOp::Maximum => set_once(&mut filter.node.max_level, key, position)?,
                    }
                }
                KeyRole::Order => {
                    let term = parse_order(table, value)?;
                    filter.order.push(term);
                }
                KeyRole::Limit => {
                    let limit = value
                        .parse()
                        .map_err(|_| Refusal::invalid(format!("invalid limit {value:?}")))?;
                    set_once(&mut filter.limit, key, limit)?;
                }
                KeyRole::Offset => {
                    let offset = value
                        .parse()
                        .map_err(|_| Refusal::invalid(format!("invalid offset {value:?}")))?;
                    set_once(&mut filter.offset, key, offset)?;
                }
            }
        }

        Ok(filter)
    }

    /// The table this filter queries.
    pub fn table(&self) -> RecordTable {
        self.table
    }

    /// The parsed limit, which callers cap before executing on the server.
    pub fn limit(&self) -> Option<u64> {
        self.limit
    }

    /// Cap the limit, defaulting an absent one, the way the route's `Limit` wrapper
    /// does. A limit above the cap is a validation error.
    pub fn with_limit_cap(mut self, cap: u64) -> Result<Self, Refusal> {
        match self.limit {
            None => self.limit = Some(cap),
            Some(limit) if limit > cap => {
                return Err(Refusal::invalid(format!(
                    "limit must be less than or equal to {cap}"
                )));
            }
            Some(_) => {}
        }

        Ok(self)
    }

    /// Build the listing statement, mirroring the Python layer's `apply`.
    pub fn statement(&self, dialect: SqlDialect) -> SelectStatement {
        let mut statement = Query::select();
        statement
            .column(Asterisk)
            .from(Alias::new(self.table.name()));
        for condition in self.node.conditions(self.table, dialect) {
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
    pub fn count_statement(&self, dialect: SqlDialect) -> SelectStatement {
        if self.limit.is_none() && self.offset.is_none() {
            let mut statement = Query::select();
            statement
                .expr(Expr::cust("COUNT(*)"))
                .from(Alias::new(self.table.name()));
            for condition in self.node.conditions(self.table, dialect) {
                statement.and_where(condition);
            }

            return statement;
        }

        let mut inner = Query::select();
        inner
            .column(Alias::new("id"))
            .from(Alias::new(self.table.name()));
        for condition in self.node.conditions(self.table, dialect) {
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

    /// The order terms, the record default of ascending timestamp when none given.
    fn order_terms(&self) -> Vec<OrderTerm> {
        if !self.order.is_empty() {
            return self.order.clone();
        }

        self.table
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

impl FilterNode {
    /// Add one equality value for a field, parsed by its family.
    fn push_equality(&mut self, field: &'static FilterField, value: &str) -> Result<(), Refusal> {
        let parsed = match field.family {
            FieldFamily::Uuid => Values::Uuids(vec![
                value
                    .parse()
                    .map_err(|_| Refusal::invalid(format!("invalid UUID {value:?}")))?,
            ]),
            // A selector modifier or a relative form is outside the compiler still. A
            // plain absolute address compiles to the equality the Python selector
            // expression reduces to, and a second one delegates rather than guessing
            // at selector semantics.
            FieldFamily::Address => {
                if !plain_address(value) {
                    return Err(Refusal::Delegated);
                }

                Values::Texts(vec![value.to_string()])
            }
            FieldFamily::Timestamp => Values::Stamps(vec![parse_timestamp(value)?]),
            FieldFamily::Text => Values::Texts(vec![value.to_string()]),
            FieldFamily::Values(admissible) => {
                if !admissible.contains(&value) {
                    return Err(Refusal::invalid(format!("invalid {} {value:?}", field.key)));
                }

                Values::Texts(vec![value.to_string()])
            }
            FieldFamily::Level => {
                level_position(value)
                    .ok_or_else(|| Refusal::invalid(format!("invalid level {value:?}")))?;
                Values::Texts(vec![value.to_string()])
            }
            FieldFamily::Bytes => Values::Bytes(vec![latin1_bytes(value)]),
            // A JSON field carries no equality key, only its operation filters, so its
            // own key never resolves here.
            FieldFamily::Json => return Err(Refusal::Delegated),
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
                        return Err(Refusal::Delegated);
                    }

                    existing.append(&mut more);
                }
                (Values::Stamps(existing), Values::Stamps(more)) => existing.extend(more),
                (Values::Bytes(existing), Values::Bytes(more)) => existing.extend(more),
                _ => return Err(Refusal::Delegated),
            },
        }

        Ok(())
    }

    /// Add one operation filter value, repeats collecting like the Python layer's
    /// list folding.
    fn push_operation(&mut self, field: &'static FilterField, kind: OperationKind, value: &str) {
        let parsed = match field.family {
            FieldFamily::Bytes => Values::Bytes(vec![latin1_bytes(value)]),
            _ => Values::Texts(vec![value.to_string()]),
        };

        let existing = self
            .operations
            .iter_mut()
            .find(|operation| operation.field.key == field.key && operation.kind == kind);
        match existing {
            None => self.operations.push(OperationFilter {
                field,
                kind,
                values: parsed,
            }),
            Some(operation) => match (&mut operation.values, parsed) {
                (Values::Texts(existing), Values::Texts(mut more)) => existing.append(&mut more),
                (Values::Bytes(existing), Values::Bytes(more)) => existing.extend(more),
                _ => unreachable!("one field's operation values share a family"),
            },
        }
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
                    Values::Bytes(patterns) => {
                        match_values(column.clone(), patterns.iter().cloned().map(Value::from))
                    }
                });
            }

            self.operation_conditions(&mut conditions, field, dialect);

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

    /// Compile one field's operation filters, in the operations' declared order.
    fn operation_conditions(
        &self,
        conditions: &mut Vec<SimpleExpr>,
        field: &'static FilterField,
        dialect: SqlDialect,
    ) {
        for operation in field.operations {
            let held = self.operations.iter().find(|candidate| {
                candidate.field.key == field.key && candidate.kind == operation.kind
            });
            let Some(held) = held else {
                continue;
            };

            let condition = match &held.values {
                Values::Texts(patterns) => {
                    // A JSON payload matches against its serialized text, so the
                    // column casts before the comparison, like the Python layer's.
                    let column = Expr::col(Alias::new(field.key));
                    let subject = if field.family == FieldFamily::Json {
                        column.cast_as(Alias::new("TEXT"))
                    } else {
                        column.into()
                    };
                    match_text_patterns(subject, held.kind, patterns, dialect)
                }
                Values::Bytes(patterns) => {
                    match_bytes_patterns(field.key, held.kind, patterns, dialect)
                }
                _ => unreachable!("operation values are text or bytes"),
            };
            conditions.push(condition);
        }
    }
}

/// Resolve what one wire key means for a table, from the entity's field families.
fn resolve(table: RecordTable, key: &str) -> Result<KeyRole, Refusal> {
    match key {
        "order" => return Ok(KeyRole::Order),
        "limit" => return Ok(KeyRole::Limit),
        "offset" => return Ok(KeyRole::Offset),
        _ => {}
    }

    for field in table.fields() {
        if field.key == key && field.family.native() {
            return Ok(KeyRole::Equality(field));
        }

        for operation in field.operations {
            if operation.key == key {
                return Ok(KeyRole::Operation(field, operation.kind));
            }
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
                    return Ok(KeyRole::Window(operator));
                }
            }
            FieldFamily::Level => {
                let [minimum, maximum] = bound_keys(field);
                if key == minimum {
                    return Ok(KeyRole::Bound(BoundOp::Minimum));
                }

                if key == maximum {
                    return Ok(KeyRole::Bound(BoundOp::Maximum));
                }
            }
            _ => {}
        }
    }

    if RecordFilter::delegated_keys(table).contains(&key) {
        return Err(Refusal::Delegated);
    }

    // The Python filter models forbid extra fields, so an unrecognized key is a
    // validation error rather than a construct awaiting its port.
    Err(Refusal::invalid(format!("unknown filter key {key:?}")))
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
///
/// The Python layer folds the repeats into a list, which then fails the field's
/// single-value validation.
fn set_once<T>(slot: &mut Option<T>, key: &str, value: T) -> Result<(), Refusal> {
    if slot.is_some() {
        return Err(Refusal::invalid(format!("{key} takes a single value")));
    }

    *slot = Some(value);
    Ok(())
}

/// Whether an address is a plain absolute one that compiles to equality.
///
/// Selector features, modifiers (`:`), multiple segments (`|`), wildcards, relative
/// forms, and whitespace, all delegate until the selector port lands.
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
///
/// Forms outside these, epoch numbers and bare dates, are valid on the wire and
/// delegate until the timestamp grammar port lands.
fn parse_timestamp(text: &str) -> Result<NaiveDateTime, Refusal> {
    if let Ok(aware) = chrono::DateTime::parse_from_rfc3339(text) {
        return Ok(aware.naive_utc());
    }

    for format in ["%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%dT%H:%M:%S%.f"] {
        if let Ok(naive) = NaiveDateTime::parse_from_str(text, format) {
            return Ok(naive);
        }
    }

    Err(Refusal::Delegated)
}

/// Parse a wire duration, the suffix grammar or bare seconds.
///
/// ISO 8601 intervals and the other forms Pydantic accepts delegate until the duration
/// grammar port lands, and every other failure delegates with them rather than
/// guessing at which of them Python would refuse.
fn parse_duration(text: &str) -> Result<Duration, Refusal> {
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
        return Err(Refusal::Delegated);
    }

    let value: f64 = number.parse().map_err(|_| Refusal::Delegated)?;
    if !value.is_finite() || value < 0.0 {
        return Err(Refusal::Delegated);
    }

    Ok(Duration::microseconds((value * scale).round() as i64))
}

/// Parse an order value, `field`, `field:asc`, or `field:desc` over the entity's
/// filterable fields.
fn parse_order(table: RecordTable, text: &str) -> Result<OrderTerm, Refusal> {
    let (base, ascending) = match text.split_once(':') {
        None => (text, true),
        Some((base, "asc")) => (base, true),
        Some((base, "desc")) => (base, false),
        Some(_) => return Err(Refusal::invalid(format!("invalid order {text:?}"))),
    };

    let field = table
        .fields()
        .iter()
        .find(|field| field.key == base)
        .ok_or_else(|| Refusal::invalid(format!("invalid order {text:?}")))?;
    if !field.family.native() {
        // Ordering by a byte or JSON column is valid on the wire and delegates until
        // those columns order natively.
        return Err(Refusal::Delegated);
    }

    Ok(OrderTerm { field, ascending })
}

/// Bytes from a wire value the way Python's `latin-1` decode with `ignore` reads it,
/// each code point one byte, anything above `U+00FF` dropped.
fn latin1_bytes(text: &str) -> Vec<u8> {
    text.chars()
        .filter_map(|character| u8::try_from(u32::from(character)).ok())
        .collect()
}

/// Escape the `LIKE` wildcards `%` and `_` with `^`, like the Python layer.
fn like_escape(text: &str) -> String {
    text.replace('%', "^%").replace('_', "^_")
}

/// Escape the characters `GLOB` treats as wildcards, so the text matches literally.
///
/// `GLOB` has no `ESCAPE` clause, a metacharacter is made literal by wrapping it in a
/// character class instead. The `[` goes first so the classes the later replacements
/// introduce stay intact.
fn glob_escape(text: &str) -> String {
    text.replace('[', "[[]")
        .replace('*', "[*]")
        .replace('?', "[?]")
}

/// Wrap an already-escaped pattern in the wildcards its kind calls for.
fn with_wildcards(text: String, kind: OperationKind, wildcard: char) -> String {
    match kind {
        OperationKind::Contains => format!("{wildcard}{text}{wildcard}"),
        OperationKind::Prefix => format!("{text}{wildcard}"),
        OperationKind::Suffix => format!("{wildcard}{text}"),
    }
}

/// The space-separated hex tokenization of a bytes value, empty bytes staying empty.
///
/// This mirrors the Python `tokenize_bytes`, whose form the PostgreSQL
/// `ceres_tokenize_bytes` function and its trigram index share, the trailing space
/// marking the last byte's token boundary.
fn tokenize_bytes(value: &[u8]) -> String {
    if value.is_empty() {
        return String::new();
    }

    let mut text = String::with_capacity(value.len() * 3);
    for byte in value {
        text.push_str(&format!("{byte:02x} "));
    }

    text
}

/// Match a text subject against patterns, `GLOB` on the SQLite family and an escaped
/// `LIKE` on PostgreSQL, like the Python `_sql_match_string`.
///
/// When every pattern is empty the whole match is true, even for a null subject,
/// which is the one place the Python layer answers with a bare `true` rather than a
/// comparison.
fn match_text_patterns(
    subject: SimpleExpr,
    kind: OperationKind,
    patterns: &[String],
    dialect: SqlDialect,
) -> SimpleExpr {
    if patterns.iter().all(|pattern| pattern.is_empty()) {
        return Expr::value(true);
    }

    patterns
        .iter()
        .map(|pattern| match dialect {
            SqlDialect::SqliteText => {
                let pattern = with_wildcards(glob_escape(pattern), kind, '*');
                subject
                    .clone()
                    .binary(BinOper::Custom("GLOB"), Expr::val(pattern))
            }
            SqlDialect::Postgres => {
                let pattern = with_wildcards(like_escape(pattern), kind, '%');
                subject.clone().like(LikeExpr::new(pattern).escape('^'))
            }
        })
        .reduce(|combined, condition| combined.or(condition))
        .expect("patterns are never empty here")
}

/// Match a bytes column against patterns, whole-byte comparisons on the SQLite family
/// and the tokenized hex its trigram index covers on PostgreSQL.
///
/// An empty pattern is contained in, starts, and ends every value, so it matches any
/// non-null one, which byte comparison against an empty needle preserves.
fn match_bytes_patterns(
    key: &'static str,
    kind: OperationKind,
    patterns: &[Vec<u8>],
    dialect: SqlDialect,
) -> SimpleExpr {
    patterns
        .iter()
        .map(|pattern| match dialect {
            SqlDialect::SqliteText => {
                let column = Expr::col(Alias::new(key));
                let needle = Expr::val(pattern.clone());
                if pattern.is_empty() {
                    return Expr::value(true);
                }

                match kind {
                    OperationKind::Contains => Func::cust(Alias::new("instr"))
                        .arg(column)
                        .arg(needle)
                        .gt(0),
                    OperationKind::Prefix => Func::cust(Alias::new("substr"))
                        .arg(column)
                        .arg(1)
                        .arg(pattern.len() as i64)
                        .eq(needle),
                    OperationKind::Suffix => Func::cust(Alias::new("substr"))
                        .arg(column)
                        .arg(-(pattern.len() as i64))
                        .eq(needle),
                }
            }
            SqlDialect::Postgres => {
                if pattern.is_empty() {
                    return Expr::value(true);
                }

                let tokens =
                    Func::cust(Alias::new("ceres_tokenize_bytes")).arg(Expr::col(Alias::new(key)));
                let pattern = with_wildcards(like_escape(&tokenize_bytes(pattern)), kind, '%');
                tokens.like(LikeExpr::new(pattern).escape('^'))
            }
        })
        .reduce(|combined, condition| combined.or(condition))
        .unwrap_or_else(|| Expr::value(false))
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
    fn unsupported_constructs_refuse_as_delegated() {
        for rejected in [
            pairs(&[("subsample", "10")]),
            pairs(&[("and", "{}")]),
            pairs(&[("address", "@a,@b")]),
            pairs(&[("address", "@a:children")]),
            pairs(&[("address", "sensor")]),
            pairs(&[("address", "@a"), ("address", "@b")]),
            pairs(&[("after", "1722340000")]),
            pairs(&[("timespan", "PT5S")]),
        ] {
            assert_eq!(
                RecordFilter::parse(RecordTable::Messages, &rejected),
                Err(Refusal::Delegated),
                "{rejected:?}"
            );
        }
    }

    #[test]
    fn invalid_values_refuse_with_a_message() {
        for rejected in [
            pairs(&[("nope", "1")]),
            pairs(&[("direction", "sideways")]),
            pairs(&[("order", "timestamp:sideways")]),
            pairs(&[("order", "nope")]),
            pairs(&[("limit", "-1")]),
            pairs(&[("limit", "5"), ("limit", "6")]),
            pairs(&[("id", "not-a-uuid")]),
        ] {
            assert!(
                matches!(
                    RecordFilter::parse(RecordTable::Messages, &rejected),
                    Err(Refusal::Invalid(_))
                ),
                "{rejected:?}"
            );
        }
    }

    #[test]
    fn per_table_keys_apply_only_to_their_tables() {
        let connection = pairs(&[("connection", "serial")]);
        assert!(RecordFilter::parse(RecordTable::Messages, &connection).is_ok());
        assert!(RecordFilter::parse(RecordTable::Particles, &connection).is_err());

        let level = pairs(&[("min_level", "warning")]);
        assert!(RecordFilter::parse(RecordTable::Alerts, &level).is_ok());
        assert!(RecordFilter::parse(RecordTable::Messages, &level).is_err());
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
            "connection_contains",
            "connection_suffix",
            "direction",
            "data",
            "contains",
            "prefix",
            "suffix",
            "order",
            "limit",
        ] {
            assert!(keys.contains(&expected), "{expected} missing");
        }

        let keys = RecordFilter::supported_keys(RecordTable::Alerts);
        for expected in ["type_contains", "data_prefix", "min_level"] {
            assert!(keys.contains(&expected), "{expected} missing");
        }

        // A JSON payload carries operation filters but no equality key of its own.
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
            .statement(SqlDialect::SqliteText)
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
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("\"level\" = 'info'"), "{sql}");

        let several = RecordFilter::parse(
            RecordTable::Logs,
            &pairs(&[("level", "info"), ("level", "error")]),
        )
        .unwrap();
        let sql = several
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("\"level\" IN ('info', 'error')"), "{sql}");
    }

    #[test]
    fn text_operations_compile_per_backend() {
        let filter = RecordFilter::parse(
            RecordTable::Alerts,
            &pairs(&[("type_contains", "temp_high"), ("type_prefix", "d[o]or")]),
        )
        .unwrap();

        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("\"type\" GLOB '*temp_high*'"), "{sql}");
        assert!(sql.contains("\"type\" GLOB 'd[[]o]or*'"), "{sql}");

        let sql = filter
            .statement(SqlDialect::Postgres)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(
            sql.contains("\"type\" LIKE '%temp^_high%' ESCAPE '^'"),
            "{sql}"
        );
        assert!(sql.contains("\"type\" LIKE 'd[o]or%' ESCAPE '^'"), "{sql}");
    }

    #[test]
    fn repeated_operation_values_combine_with_or() {
        let filter = RecordFilter::parse(
            RecordTable::Logs,
            &pairs(&[("contains", "warm"), ("contains", "cold")]),
        )
        .unwrap();

        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains("(\"content\" GLOB '*warm*') OR (\"content\" GLOB '*cold*')"),
            "{sql}"
        );
    }

    #[test]
    fn json_operations_match_the_serialized_text() {
        let filter =
            RecordFilter::parse(RecordTable::Alerts, &pairs(&[("data_contains", "sensor")]))
                .unwrap();

        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains("CAST(\"data\" AS TEXT) GLOB '*sensor*'"),
            "{sql}"
        );
    }

    #[test]
    fn bytes_operations_compile_whole_byte_matches() {
        let filter = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("contains", "ab"), ("prefix", "x"), ("suffix", "yz")]),
        )
        .unwrap();

        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("instr(\"data\", x'6162') > 0"), "{sql}");
        assert!(sql.contains("substr(\"data\", 1, 1) = x'78'"), "{sql}");
        assert!(sql.contains("substr(\"data\", -2) = x'797A'"), "{sql}");

        let sql = filter
            .statement(SqlDialect::Postgres)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(
            sql.contains("ceres_tokenize_bytes(\"data\") LIKE '%61 62 %' ESCAPE '^'"),
            "{sql}"
        );
        assert!(
            sql.contains("ceres_tokenize_bytes(\"data\") LIKE '78 %' ESCAPE '^'"),
            "{sql}"
        );
        assert!(
            sql.contains("ceres_tokenize_bytes(\"data\") LIKE '%79 7a ' ESCAPE '^'"),
            "{sql}"
        );
    }

    #[test]
    fn bytes_equality_binds_the_stored_blob() {
        let filter = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("data", "ab"), ("data", "cd")]),
        )
        .unwrap();

        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("\"data\" IN (x'6162', x'6364')"), "{sql}");
    }

    #[test]
    fn empty_patterns_match_like_the_python_layer() {
        // All-empty text patterns collapse to a bare true.
        let all_empty =
            RecordFilter::parse(RecordTable::Logs, &pairs(&[("contains", "")])).unwrap();
        let sql = all_empty
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("WHERE TRUE"), "{sql}");

        // A mixed set keeps the empty pattern as a wildcard-only match.
        let mixed = RecordFilter::parse(
            RecordTable::Logs,
            &pairs(&[("contains", ""), ("contains", "x")]),
        )
        .unwrap();
        let sql = mixed
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains("(\"content\" GLOB '**') OR (\"content\" GLOB '*x*')"),
            "{sql}"
        );
    }

    #[test]
    fn bytes_columns_order_natively() {
        let filter =
            RecordFilter::parse(RecordTable::Messages, &pairs(&[("order", "data:desc")])).unwrap();
        let sql = filter
            .statement(SqlDialect::Postgres)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(sql.contains("ORDER BY \"data\" DESC"), "{sql}");
    }

    #[test]
    fn bounded_counts_page_before_counting() {
        let filter =
            RecordFilter::parse(RecordTable::Particles, &pairs(&[("limit", "5")])).unwrap();
        let sql = filter
            .count_statement(SqlDialect::SqliteText)
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
            .statement(SqlDialect::Postgres)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(sql.contains("ORDER BY \"id\" ASC"), "{sql}");

        let by_content =
            RecordFilter::parse(RecordTable::Logs, &pairs(&[("order", "content:desc")])).unwrap();
        let sql = by_content
            .statement(SqlDialect::Postgres)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(
            sql.contains("ORDER BY \"content\" COLLATE \"C\" DESC"),
            "{sql}"
        );
    }

    #[test]
    fn durations_parse_the_suffix_grammar() {
        assert_eq!(parse_duration("5s"), Ok(Duration::seconds(5)));
        assert_eq!(parse_duration("1.5 h"), Ok(Duration::seconds(5400)));
        assert_eq!(parse_duration("100ms"), Ok(Duration::milliseconds(100)));
        assert_eq!(parse_duration("7d"), Ok(Duration::days(7)));
        assert_eq!(parse_duration("90"), Ok(Duration::seconds(90)));
        assert_eq!(parse_duration("PT5S"), Err(Refusal::Delegated));
        assert_eq!(parse_duration("-5s"), Err(Refusal::Delegated));
        assert_eq!(parse_duration("week"), Err(Refusal::Delegated));
    }

    #[test]
    fn limits_cap_and_default_like_the_route_wrapper() {
        let filter = RecordFilter::parse(RecordTable::Messages, &pairs(&[])).unwrap();
        assert_eq!(filter.with_limit_cap(1000).unwrap().limit(), Some(1000));

        let low = RecordFilter::parse(RecordTable::Messages, &pairs(&[("limit", "5")])).unwrap();
        assert_eq!(low.with_limit_cap(1000).unwrap().limit(), Some(5));

        let high =
            RecordFilter::parse(RecordTable::Messages, &pairs(&[("limit", "5000")])).unwrap();
        assert!(high.with_limit_cap(1000).is_err());
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
