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

use serde_norway::Value as Yaml;

use crate::records::RecordTable;
use crate::selector::{AddressSelector, valid_address};
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
    /// The root address that relative selector segments resolve against.
    Root,
    /// An `or` or `and` group of recursive subfilters.
    Group(GroupOp),
    /// One of the subsampling controls a record's timestamp brings.
    Subsample(SubsampleOp),
    /// One of the window operators a timestamp field brings.
    Window(WindowOp),
    /// One of the time-of-day windows a timestamp field brings.
    Clock(ClockOp),
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
enum SubsampleOp {
    Every,
    Count,
    Select,
}

/// Which record each subsample bucket keeps.
#[derive(Clone, Copy, Debug, PartialEq)]
enum SubsampleSelect {
    First,
    Last,
}

#[derive(Clone, Copy, PartialEq)]
enum GroupOp {
    Or,
    And,
}

#[derive(Clone, Copy, PartialEq)]
enum ClockOp {
    AfterHour,
    BeforeHour,
    AfterMinute,
    BeforeMinute,
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
    /// The address selector, every `address` value's segments folded together.
    address: Option<AddressSelector>,
    /// The root relative selector segments resolve against.
    root: Option<String>,
    after: Option<NaiveDateTime>,
    before: Option<NaiveDateTime>,
    timespan: Option<Duration>,
    max_age: Option<Duration>,
    min_age: Option<Duration>,
    /// Subsampling, at most one record kept per time bucket.
    subsample_every: Option<Duration>,
    subsample: Option<u64>,
    subsample_select: Option<SubsampleSelect>,
    /// Time-of-day windows over the timestamp's hour and minute, wrapping around
    /// midnight when the lower bound exceeds the upper.
    after_hour: Option<u32>,
    before_hour: Option<u32>,
    after_minute: Option<u32>,
    before_minute: Option<u32>,
    /// Level bounds as indexes into the level family's ordered values.
    min_level: Option<usize>,
    max_level: Option<usize>,
    /// Whether the node can match at all, an explicitly empty value list matching
    /// nothing the way the Python layer's empty `IN` does.
    impossible: bool,
    /// Subfilter groups, every `and` node's conditions holding with this node's and
    /// any `or` node matching on its own.
    and_children: Vec<FilterNode>,
    or_children: Vec<FilterNode>,
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
                FieldFamily::Address => {
                    keys.push("root");
                }
                FieldFamily::Timestamp => {
                    keys.extend(["after", "before", "timespan", "max_age", "min_age"]);
                    keys.extend(["after_hour", "before_hour", "after_minute", "before_minute"]);
                    keys.extend(["subsample_every", "subsample", "subsample_select"]);
                }
                FieldFamily::Level => {
                    keys.extend(bound_keys(field));
                }
                _ => {}
            }
        }

        keys.extend(["order", "limit", "offset", "or", "and"]);
        keys
    }

    /// The filter keys the compiler knowingly delegates for a table.
    ///
    /// What remains is Python's structural query filters, shared by every table, plus
    /// its Python-only constructs, and the classification test holds the union of this
    /// list and the supported one to exactly what the Pydantic models declare so a new
    /// filter field cannot ship unclassified.
    pub fn delegated_keys(table: RecordTable) -> Vec<&'static str> {
        // A particle's `class` filters by a Python type, which has no native form.
        if table == RecordTable::Particles {
            return vec!["class"];
        }

        Vec::new()
    }

    /// Parse query pairs into a filter, refusing what cannot compile natively.
    ///
    /// Repeated keys collect into lists, matching how the Python layer folds ordered
    /// pairs before validating.
    pub fn parse(table: RecordTable, pairs: &[(String, String)]) -> Result<Self, Refusal> {
        let mut parsed = Parsed::default();
        for (key, value) in pairs {
            parsed.apply(table, key, &WireValue::Text(value))?;
        }

        let Parsed {
            node,
            order,
            limit,
            offset,
            ..
        } = parsed.finish()?;
        Ok(Self {
            table,
            node,
            order,
            limit,
            offset,
        })
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

    /// Parse a filter from its serialized JSON form, the Python filter model's dump.
    ///
    /// JSON is a YAML subset, so this reads through the same parser the subfilter
    /// values use, one grammar for every front-end.
    pub fn from_json(table: RecordTable, text: &str) -> Result<Self, Refusal> {
        let value = parse_yaml(text)?;
        let Yaml::Mapping(mapping) = value else {
            return Err(Refusal::invalid("a filter must be a mapping"));
        };

        let Parsed {
            node,
            order,
            limit,
            offset,
            ..
        } = Parsed::from_yaml(table, &mapping)?;
        Ok(Self {
            table,
            node,
            order,
            limit,
            offset,
        })
    }

    /// Compile to SQL and its bound parameters, in the dialect's placeholder style.
    ///
    /// The parameters arrive in placeholder order, ready for a driver-level execute,
    /// `?` for the SQLite family and `$n` for PostgreSQL.
    pub fn compiled(&self, dialect: SqlDialect, count: bool) -> (String, Vec<Value>) {
        let statement = if count {
            self.count_statement(dialect)
        } else {
            self.statement(dialect)
        };
        let (sql, values) = match dialect {
            SqlDialect::SqliteText => statement.build(sea_query::SqliteQueryBuilder),
            SqlDialect::Postgres => statement.build(sea_query::PostgresQueryBuilder),
        };
        (sql, values.0)
    }

    /// Whether one serialized record matches this filter, like the Python filter's
    /// `matches`.
    ///
    /// Query controls and subsampling do not participate, this reads a single record
    /// the way live stream filtering does. Age-relative conditions compare against
    /// the moment of the call.
    pub fn matches(&self, record_json: &str) -> Result<bool, String> {
        let fields: std::collections::HashMap<&str, &serde_json::value::RawValue> =
            serde_json::from_str(record_json)
                .map_err(|error| format!("unreadable record: {error}"))?;
        let now = Utc::now().naive_utc().trunc_subsecs(6);
        Ok(self.node.matches(self.table, &fields, now))
    }

    /// Build the listing statement, mirroring the Python layer's `apply`.
    pub fn statement(&self, dialect: SqlDialect) -> SelectStatement {
        // `now` truncates to microseconds so arithmetic and rendering match Python's
        // `datetime` resolution exactly, and every node shares one instant.
        let now = Utc::now().naive_utc().trunc_subsecs(6);
        let mut statement = Query::select();
        statement
            .column(Asterisk)
            .from(Alias::new(self.table.name()));
        for condition in self.node.combined_conditions(self.table, dialect, now) {
            statement.and_where(condition);
        }

        for term in self.order_terms() {
            order_by(&mut statement, term, dialect);
        }

        if let Some(limit) = self.limit {
            statement.limit(limit);
        } else if self.offset.is_some() && dialect == SqlDialect::SqliteText {
            // SQLite refuses a bare `OFFSET`, so an unlimited query names the limit
            // SQLAlchemy would, one no result set reaches.
            statement.limit(i64::MAX as u64);
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
        let now = Utc::now().naive_utc().trunc_subsecs(6);
        if self.limit.is_none() && self.offset.is_none() {
            let mut statement = Query::select();
            statement
                .expr(Expr::cust("COUNT(*)"))
                .from(Alias::new(self.table.name()));
            for condition in self.node.combined_conditions(self.table, dialect, now) {
                statement.and_where(condition);
            }

            return statement;
        }

        let mut inner = Query::select();
        inner
            .column(Alias::new("id"))
            .from(Alias::new(self.table.name()));
        for condition in self.node.combined_conditions(self.table, dialect, now) {
            inner.and_where(condition);
        }

        for term in self.order_terms() {
            order_by(&mut inner, term, dialect);
        }

        if let Some(limit) = self.limit {
            inner.limit(limit);
        } else if self.offset.is_some() && dialect == SqlDialect::SqliteText {
            inner.limit(i64::MAX as u64);
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

/// One wire value mid-parse, plain text from query pairs or YAML from a subfilter.
enum WireValue<'a> {
    Text(&'a str),
    Yaml(&'a Yaml),
}

impl WireValue<'_> {
    /// The value as one scalar, refusing lists where the wire takes a single value.
    fn scalar(&self, key: &str) -> Result<String, Refusal> {
        match self {
            Self::Text(text) => Ok((*text).to_string()),
            Self::Yaml(value) => {
                yaml_scalar(value).ok_or_else(|| Refusal::invalid(format!("invalid {key} value")))
            }
        }
    }

    /// The value as the scalars it lists, one for plain text.
    fn scalars(&self, key: &str) -> Result<Vec<String>, Refusal> {
        match self {
            Self::Text(text) => Ok(vec![(*text).to_string()]),
            Self::Yaml(Yaml::Sequence(elements)) => elements
                .iter()
                .map(|element| {
                    yaml_scalar(element)
                        .ok_or_else(|| Refusal::invalid(format!("invalid {key} value")))
                })
                .collect(),
            Self::Yaml(value) => yaml_scalar(value)
                .map(|scalar| vec![scalar])
                .ok_or_else(|| Refusal::invalid(format!("invalid {key} value"))),
        }
    }
}

/// One YAML scalar in the text form the wire parsers read, `None` for the rest.
///
/// Booleans stay out deliberately, the Python filter fields reject them everywhere a
/// scalar is expected.
fn yaml_scalar(value: &Yaml) -> Option<String> {
    match value {
        Yaml::String(text) => Some(text.clone()),
        Yaml::Number(number) => Some(number.to_string()),
        _ => None,
    }
}

/// Parse one wire YAML value the way the Python `FromYAML` reads it, empty text
/// reading as null.
fn parse_yaml(text: &str) -> Result<Yaml, Refusal> {
    if text.trim().is_empty() {
        return Ok(Yaml::Null);
    }

    serde_norway::from_str(text).map_err(|_| Refusal::invalid(format!("invalid YAML {text:?}")))
}

/// A filter node mid-parse, its query controls and subfilter groups still attached.
///
/// A subfilter can carry `order`, `limit`, and `offset`, which hoist into its parent
/// under the Python model's rules rather than compiling as conditions, so they ride
/// here until the node finishes.
#[derive(Default)]
struct Parsed {
    node: FilterNode,
    order: Vec<OrderTerm>,
    limit: Option<u64>,
    offset: Option<u64>,
    and_group: Vec<Parsed>,
    or_group: Vec<Parsed>,
}

impl Parsed {
    /// Apply one wire key to this node.
    fn apply(&mut self, table: RecordTable, key: &str, value: &WireValue) -> Result<(), Refusal> {
        match resolve(table, key)? {
            KeyRole::Equality(field) => {
                let scalars = value.scalars(key)?;
                if scalars.is_empty() {
                    self.node.impossible = true;
                }

                for scalar in scalars {
                    self.node.push_equality(field, &scalar)?;
                }
            }
            KeyRole::Operation(field, kind) => {
                let scalars = value.scalars(key)?;
                if scalars.is_empty() {
                    self.node.impossible = true;
                }

                for scalar in scalars {
                    self.node.push_operation(field, kind, &scalar);
                }
            }
            KeyRole::Root => {
                let value = value.scalar(key)?;
                if !valid_address(&value) {
                    return Err(Refusal::invalid(format!("invalid root {value:?}")));
                }

                set_once(&mut self.node.root, key, value)?;
            }
            KeyRole::Group(operator) => {
                let children = group_children(table, value)?;
                match operator {
                    GroupOp::And => self.and_group.extend(children),
                    GroupOp::Or => self.or_group.extend(children),
                }
            }
            KeyRole::Window(operator) => {
                let value = value.scalar(key)?;
                match operator {
                    WindowOp::After => {
                        set_once(&mut self.node.after, key, parse_timestamp(&value)?)?;
                    }
                    WindowOp::Before => {
                        set_once(&mut self.node.before, key, parse_timestamp(&value)?)?;
                    }
                    WindowOp::Timespan => {
                        let timespan = parse_duration(&value)?;
                        if timespan < Duration::microseconds(1) {
                            return Err(Refusal::invalid("timespan must be greater than zero"));
                        }

                        set_once(&mut self.node.timespan, key, timespan)?;
                    }
                    WindowOp::MaxAge => {
                        set_once(&mut self.node.max_age, key, parse_duration(&value)?)?;
                    }
                    WindowOp::MinAge => {
                        set_once(&mut self.node.min_age, key, parse_duration(&value)?)?;
                    }
                }
            }
            KeyRole::Subsample(operator) => {
                let value = value.scalar(key)?;
                match operator {
                    SubsampleOp::Every => {
                        let every = parse_duration(&value)?;
                        if every < Duration::microseconds(1) {
                            return Err(Refusal::invalid(
                                "subsample_every must be greater than zero",
                            ));
                        }

                        set_once(&mut self.node.subsample_every, key, every)?;
                    }
                    SubsampleOp::Count => {
                        let count: u64 = value
                            .parse()
                            .ok()
                            .filter(|count| *count >= 1)
                            .ok_or_else(|| {
                                Refusal::invalid(format!("invalid subsample {value:?}"))
                            })?;
                        set_once(&mut self.node.subsample, key, count)?;
                    }
                    SubsampleOp::Select => {
                        let select = match value.as_str() {
                            "first" => SubsampleSelect::First,
                            "last" => SubsampleSelect::Last,
                            _ => {
                                return Err(Refusal::invalid(format!(
                                    "invalid subsample_select {value:?}"
                                )));
                            }
                        };
                        set_once(&mut self.node.subsample_select, key, select)?;
                    }
                }
            }
            KeyRole::Clock(operator) => {
                let value = value.scalar(key)?;
                let cap = match operator {
                    ClockOp::AfterHour | ClockOp::BeforeHour => 24,
                    ClockOp::AfterMinute | ClockOp::BeforeMinute => 60,
                };
                let bound: u32 = value
                    .parse()
                    .ok()
                    .filter(|bound| *bound <= cap)
                    .ok_or_else(|| Refusal::invalid(format!("invalid {key} {value:?}")))?;
                let slot = match operator {
                    ClockOp::AfterHour => &mut self.node.after_hour,
                    ClockOp::BeforeHour => &mut self.node.before_hour,
                    ClockOp::AfterMinute => &mut self.node.after_minute,
                    ClockOp::BeforeMinute => &mut self.node.before_minute,
                };
                set_once(slot, key, bound)?;
            }
            KeyRole::Bound(operator) => {
                let value = value.scalar(key)?;
                let position = level_position(&value)
                    .ok_or_else(|| Refusal::invalid(format!("invalid level {value:?}")))?;
                match operator {
                    BoundOp::Minimum => set_once(&mut self.node.min_level, key, position)?,
                    BoundOp::Maximum => set_once(&mut self.node.max_level, key, position)?,
                }
            }
            KeyRole::Order => {
                for scalar in value.scalars(key)? {
                    self.order.push(parse_order(table, &scalar)?);
                }
            }
            KeyRole::Limit => {
                let value = value.scalar(key)?;
                let limit = value
                    .parse()
                    .map_err(|_| Refusal::invalid(format!("invalid limit {value:?}")))?;
                set_once(&mut self.limit, key, limit)?;
            }
            KeyRole::Offset => {
                let value = value.scalar(key)?;
                let offset = value
                    .parse()
                    .map_err(|_| Refusal::invalid(format!("invalid offset {value:?}")))?;
                set_once(&mut self.offset, key, offset)?;
            }
        }

        Ok(())
    }

    /// Parse one subfilter from its YAML mapping.
    fn from_yaml(table: RecordTable, mapping: &serde_norway::Mapping) -> Result<Self, Refusal> {
        let mut parsed = Self::default();
        for (key, value) in mapping {
            let Some(key) = key.as_str() else {
                return Err(Refusal::invalid("subfilter keys must be strings"));
            };

            // A null value leaves its field unset, like the Python models.
            if matches!(value, Yaml::Null) {
                continue;
            }

            parsed.apply(table, key, &WireValue::Yaml(value))?;
        }

        parsed.finish()
    }

    /// Finish the node, checking the `or` group's restrictions and hoisting the `and`
    /// group's query controls, exactly as the Python model validator does.
    fn finish(mut self) -> Result<Self, Refusal> {
        // A count-based subsample needs a bounded time range, and whether one exists
        // follows from which range fields are set, never from the clock.
        if self.node.subsample.is_some() {
            let has_start = self.node.after.is_some()
                || self.node.timespan.is_some()
                || self.node.max_age.is_some();
            let has_end = self.node.before.is_some()
                || self.node.timespan.is_some()
                || self.node.min_age.is_some();
            if !has_start || !has_end {
                let subject = match (has_start, has_end) {
                    (false, false) => "Start and end time",
                    (false, true) => "Start time",
                    _ => "End time",
                };
                return Err(Refusal::invalid(format!(
                    "{subject} for `subsample` time range could not be determined."
                )));
            }
        }

        for child in &self.or_group {
            for (name, present) in [
                ("order", !child.order.is_empty()),
                ("limit", child.limit.is_some()),
                ("offset", child.offset.is_some()),
            ] {
                if present {
                    return Err(Refusal::invalid(format!(
                        "Cannot specify `{name}` in `or__` subfilters. Use `and__` instead."
                    )));
                }
            }
        }

        for child in std::mem::take(&mut self.and_group) {
            let Parsed {
                node,
                order,
                limit,
                offset,
                ..
            } = child;
            // The last ordering wins, the tightest limit and the deepest offset hold.
            if !order.is_empty() {
                self.order = order;
            }

            if let Some(limit) = limit {
                self.limit = Some(self.limit.map_or(limit, |own| own.min(limit)));
            }

            if let Some(offset) = offset {
                self.offset = Some(self.offset.map_or(offset, |own| own.max(offset)));
            }

            self.node.and_children.push(node);
        }

        for child in std::mem::take(&mut self.or_group) {
            self.node.or_children.push(child.node);
        }

        Ok(self)
    }
}

/// The subfilters one `or` or `and` wire value carries.
///
/// A plain text value parses as YAML first. The result is one subfilter mapping, a
/// sequence of them, or nothing, and a sequence element may itself be YAML text of
/// one mapping, the way the Python `FromYAML` layers read it.
fn group_children(table: RecordTable, value: &WireValue) -> Result<Vec<Parsed>, Refusal> {
    let parsed;
    let value = match value {
        WireValue::Text(text) => {
            parsed = parse_yaml(text)?;
            &parsed
        }
        WireValue::Yaml(value) => *value,
    };

    let one = |element: &Yaml| -> Result<Parsed, Refusal> {
        let parsed;
        let element = match element {
            Yaml::String(text) => {
                parsed = parse_yaml(text)?;
                &parsed
            }
            _ => element,
        };
        match element {
            Yaml::Mapping(mapping) => Parsed::from_yaml(table, mapping),
            _ => Err(Refusal::invalid("a subfilter must be a mapping")),
        }
    };

    match value {
        Yaml::Null => Ok(Vec::new()),
        Yaml::Sequence(elements) => elements.iter().map(one).collect(),
        other => Ok(vec![one(other)?]),
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
            // An address filters through the selector grammar, repeated values folding
            // into more segments.
            FieldFamily::Address => {
                let selector = self.address.get_or_insert_with(AddressSelector::default);
                return selector.push(value).map_err(Refusal::Invalid);
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
                (Values::Texts(existing), Values::Texts(mut more)) => existing.append(&mut more),
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

    /// Whether a record matches this node's tree, its own conditions and every `and`
    /// node holding, or any `or` node holding on its own.
    fn matches(
        &self,
        table: RecordTable,
        fields: &std::collections::HashMap<&str, &serde_json::value::RawValue>,
        now: NaiveDateTime,
    ) -> bool {
        (self.matches_own(table, fields, now)
            && self
                .and_children
                .iter()
                .all(|child| child.matches(table, fields, now)))
            || self
                .or_children
                .iter()
                .any(|child| child.matches(table, fields, now))
    }

    /// Whether a record satisfies this node's own conditions.
    fn matches_own(
        &self,
        table: RecordTable,
        fields: &std::collections::HashMap<&str, &serde_json::value::RawValue>,
        now: NaiveDateTime,
    ) -> bool {
        if self.impossible {
            return false;
        }

        for field in table.fields() {
            let raw = fields.get(field.key).copied();
            let text = raw.and_then(|raw| serde_json::from_str::<String>(raw.get()).ok());

            if let Some(values) = self.values_of(field) {
                let held = match (values, field.family) {
                    (Values::Uuids(ids), _) => text
                        .as_deref()
                        .is_some_and(|text| ids.iter().any(|id| id.to_string() == text)),
                    (Values::Stamps(stamps), _) => record_timestamp(text.as_deref())
                        .is_some_and(|stamp| stamps.contains(&stamp)),
                    (Values::Bytes(patterns), _) => text
                        .as_deref()
                        .is_some_and(|text| patterns.contains(&latin1_bytes(text))),
                    (Values::Texts(texts), _) => text
                        .as_deref()
                        .is_some_and(|text| texts.iter().any(|candidate| candidate == text)),
                };
                if !held {
                    return false;
                }
            }

            if field.family == FieldFamily::Address
                && let Some(selector) = &self.address
            {
                let held = text
                    .as_deref()
                    .is_some_and(|text| selector.matches(text, self.root.as_deref()));
                if !held {
                    return false;
                }
            }

            for operation in field.operations {
                let held_values = self.operations.iter().find(|candidate| {
                    candidate.field.key == field.key && candidate.kind == operation.kind
                });
                let Some(held_values) = held_values else {
                    continue;
                };

                let matched = match &held_values.values {
                    Values::Texts(patterns) => {
                        // A JSON payload matches within its serialized text, other
                        // fields within their value.
                        let subject = if field.family == FieldFamily::Json {
                            raw.map(|raw| raw.get().to_string())
                        } else {
                            text.clone()
                        };
                        subject.as_deref().is_some_and(|subject| {
                            patterns
                                .iter()
                                .any(|pattern| text_matches(subject, held_values.kind, pattern))
                        })
                    }
                    Values::Bytes(patterns) => text.as_deref().is_some_and(|text| {
                        let value = latin1_bytes(text);
                        patterns
                            .iter()
                            .any(|pattern| bytes_match(&value, held_values.kind, pattern))
                    }),
                    _ => false,
                };
                if !matched {
                    return false;
                }
            }

            match field.family {
                FieldFamily::Timestamp => {
                    let Some(stamp) = record_timestamp(text.as_deref()) else {
                        if self.needs_timestamp() {
                            return false;
                        }

                        continue;
                    };
                    if !self.timestamp_matches(stamp, now) {
                        return false;
                    }
                }
                FieldFamily::Level => {
                    let position = text.as_deref().and_then(level_position);
                    if let Some(minimum) = self.min_level
                        && !position.is_some_and(|position| position >= minimum)
                    {
                        return false;
                    }

                    if let Some(maximum) = self.max_level
                        && !position.is_some_and(|position| position <= maximum)
                    {
                        return false;
                    }
                }
                _ => {}
            }
        }

        true
    }

    /// Whether any timestamp condition is set on this node.
    fn needs_timestamp(&self) -> bool {
        self.after.is_some()
            || self.before.is_some()
            || self.timespan.is_some()
            || self.max_age.is_some()
            || self.min_age.is_some()
            || self.after_hour.is_some()
            || self.before_hour.is_some()
            || self.after_minute.is_some()
            || self.before_minute.is_some()
    }

    /// Whether a record's timestamp satisfies the window and age conditions.
    fn timestamp_matches(&self, stamp: NaiveDateTime, now: NaiveDateTime) -> bool {
        if let Some(after) = self.after
            && stamp < after
        {
            return false;
        }

        if let Some(before) = self.before
            && stamp >= before
        {
            return false;
        }

        if let Some(timespan) = self.timespan {
            if let Some(after) = self.after {
                if stamp >= after + timespan {
                    return false;
                }
            } else if let Some(before) = self.before {
                if stamp < before - timespan {
                    return false;
                }
            } else if stamp < now - timespan || stamp >= now {
                return false;
            }
        }

        if let Some(max_age) = self.max_age
            && stamp <= now - max_age
        {
            return false;
        }

        if let Some(min_age) = self.min_age
            && stamp > now - min_age
        {
            return false;
        }

        use chrono::Timelike;

        let windows = [
            (self.after_hour, self.before_hour, 24, stamp.hour()),
            (self.after_minute, self.before_minute, 60, stamp.minute()),
        ];
        for (after, before, span, value) in windows {
            if after.is_none() && before.is_none() {
                continue;
            }

            let minimum = after.unwrap_or(0);
            let maximum = before.unwrap_or(span);
            let within_minimum = value >= minimum;
            let within_maximum = value < maximum;
            let held = if minimum <= maximum {
                within_minimum && within_maximum
            } else {
                within_minimum || within_maximum
            };
            if !held {
                return false;
            }
        }

        true
    }

    /// This node's conditions joined with its subfilter groups', one condition when
    /// an `or` group needs the whole set to nest inside it.
    ///
    /// Every `and` node's conditions extend this node's. An `or` node matches on its
    /// own, its conditions grouped so they hold together, and one with no conditions
    /// matches everything.
    fn combined_conditions(
        &self,
        table: RecordTable,
        dialect: SqlDialect,
        now: NaiveDateTime,
    ) -> Vec<SimpleExpr> {
        let mut ands = self.conditions(table, dialect, now);
        for child in &self.and_children {
            ands.extend(child.combined_conditions(table, dialect, now));
        }

        if self.or_children.is_empty() {
            return ands;
        }

        let mut terms = Vec::new();
        if !ands.is_empty() {
            terms.push(all_of(ands));
        }

        for child in &self.or_children {
            let grouped = child.combined_conditions(table, dialect, now);
            terms.push(if grouped.is_empty() {
                Expr::value(true)
            } else {
                all_of(grouped)
            });
        }

        vec![
            terms
                .into_iter()
                .reduce(|combined, term| combined.or(term))
                .expect("an or group always carries terms"),
        ]
    }

    /// The `WHERE` conditions, in the entity's field order.
    fn conditions(
        &self,
        table: RecordTable,
        dialect: SqlDialect,
        now: NaiveDateTime,
    ) -> Vec<SimpleExpr> {
        let mut conditions = Vec::new();
        if self.impossible {
            conditions.push(Expr::value(false));
        }

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

            if field.family == FieldFamily::Address
                && let Some(selector) = &self.address
            {
                conditions.push(selector.condition(field.key, self.root.as_deref(), dialect));
            }

            match field.family {
                FieldFamily::Timestamp => {
                    self.window_conditions(&mut conditions, &column, now, dialect);
                    self.subsample_conditions(&mut conditions, table, field.key, now, dialect);
                    self.clock_conditions(&mut conditions, field.key, dialect);
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

    /// The effective start and end of the node's time range, like the Python
    /// `_get_time_bounds`, the tightest bound winning on each side.
    fn time_bounds(&self, now: NaiveDateTime) -> (Option<NaiveDateTime>, Option<NaiveDateTime>) {
        let mut starts = Vec::new();
        let mut ends = Vec::new();
        if let Some(after) = self.after {
            starts.push(after);
        }

        if let Some(before) = self.before {
            ends.push(before);
        }

        if let Some(timespan) = self.timespan {
            if let Some(after) = self.after {
                ends.push(after + timespan);
            } else if let Some(before) = self.before {
                starts.push(before - timespan);
            } else {
                starts.push(now - timespan);
                ends.push(now);
            }
        }

        if let Some(max_age) = self.max_age {
            starts.push(now - max_age);
        }

        if let Some(min_age) = self.min_age {
            ends.push(now - min_age);
        }

        (starts.into_iter().max(), ends.into_iter().min())
    }

    /// The subsampling conditions, each a membership test against the timestamps the
    /// buckets keep.
    ///
    /// Both controls group the table's rows into fixed-width buckets measured from an
    /// origin and keep the first or last timestamp of each, so the condition is one
    /// grouped subquery per control.
    fn subsample_conditions(
        &self,
        conditions: &mut Vec<SimpleExpr>,
        table: RecordTable,
        key: &'static str,
        now: NaiveDateTime,
        dialect: SqlDialect,
    ) {
        if self.subsample_every.is_none() && self.subsample.is_none() {
            return;
        }

        let (start, end) = self.time_bounds(now);
        let select = self.subsample_select.unwrap_or(SubsampleSelect::First);

        if let Some(every) = self.subsample_every {
            // With no start the buckets measure from the day's midnight.
            let origin =
                start.unwrap_or_else(|| now.date().and_hms_opt(0, 0, 0).expect("midnight exists"));
            let width = every
                .num_microseconds()
                .expect("durations parse within range")
                .max(1);
            conditions.push(bucket_condition(
                table, key, origin, width, start, end, select, dialect,
            ));
        }

        if let Some(count) = self.subsample {
            // Validation guaranteed both bounds.
            let (Some(start), Some(end)) = (start, end) else {
                return;
            };
            let total = (end - start).num_microseconds().unwrap_or(0);
            let width = divide_rounding_half_even(total, count.max(1) as i64).max(1);
            conditions.push(bucket_condition(
                table,
                key,
                start,
                width,
                Some(start),
                Some(end),
                select,
                dialect,
            ));
        }
    }

    /// The time-of-day window conditions on the timestamp column.
    ///
    /// A window whose lower bound exceeds its upper wraps around midnight, so the two
    /// comparisons join with `OR` instead of `AND`, like the in-memory matching.
    fn clock_conditions(
        &self,
        conditions: &mut Vec<SimpleExpr>,
        key: &'static str,
        dialect: SqlDialect,
    ) {
        let windows = [
            (self.after_hour, self.before_hour, 24, "hour", "%H"),
            (self.after_minute, self.before_minute, 60, "minute", "%M"),
        ];
        for (after, before, span, part, format) in windows {
            if after.is_none() && before.is_none() {
                continue;
            }

            let minimum = after.unwrap_or(0);
            let maximum = before.unwrap_or(span);
            let value = clock_part(key, part, format, dialect);
            let within_minimum = value.clone().gte(minimum);
            let within_maximum = value.lt(maximum);
            if minimum <= maximum {
                conditions.push(within_minimum.and(within_maximum));
            } else {
                conditions.push(within_minimum.or(within_maximum));
            }
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
        "or" => return Ok(KeyRole::Group(GroupOp::Or)),
        "and" => return Ok(KeyRole::Group(GroupOp::And)),
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
            FieldFamily::Address if key == "root" => {
                return Ok(KeyRole::Root);
            }
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

                let operator = match key {
                    "after_hour" => Some(ClockOp::AfterHour),
                    "before_hour" => Some(ClockOp::BeforeHour),
                    "after_minute" => Some(ClockOp::AfterMinute),
                    "before_minute" => Some(ClockOp::BeforeMinute),
                    _ => None,
                };
                if let Some(operator) = operator {
                    return Ok(KeyRole::Clock(operator));
                }

                let operator = match key {
                    "subsample_every" => Some(SubsampleOp::Every),
                    "subsample" => Some(SubsampleOp::Count),
                    "subsample_select" => Some(SubsampleOp::Select),
                    _ => None,
                };
                if let Some(operator) = operator {
                    return Ok(KeyRole::Subsample(operator));
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

/// The parsing configuration Pydantic uses, extra fraction digits truncating rather
/// than erroring.
fn speedate_config() -> speedate::TimeConfig {
    speedate::TimeConfigBuilder::new()
        .microseconds_precision_overflow_behavior(
            speedate::MicrosecondsPrecisionOverflowBehavior::Truncate,
        )
        .build()
}

/// Parse a wire timestamp on the grammar the Python `DateTime` accepts, ISO forms,
/// epoch numbers, and bare dates, aware values normalizing to UTC and naive ones read
/// as UTC.
fn parse_timestamp(text: &str) -> Result<NaiveDateTime, Refusal> {
    let config = speedate::DateTimeConfig {
        time_config: speedate_config(),
        ..Default::default()
    };
    if let Ok(datetime) = speedate::DateTime::parse_str_with_config(text, &config) {
        let date = chrono::NaiveDate::from_ymd_opt(
            i32::from(datetime.date.year),
            u32::from(datetime.date.month),
            u32::from(datetime.date.day),
        );
        let naive = date.and_then(|date| {
            date.and_hms_micro_opt(
                u32::from(datetime.time.hour),
                u32::from(datetime.time.minute),
                u32::from(datetime.time.second),
                datetime.time.microsecond,
            )
        });
        if let Some(naive) = naive {
            let offset = Duration::seconds(i64::from(datetime.time.tz_offset.unwrap_or(0)));
            return Ok(naive - offset);
        }
    }

    // A bare date reads as midnight UTC, matching the Python validator's fallback.
    if let Ok(date) = speedate::Date::parse_str(text) {
        let midnight = chrono::NaiveDate::from_ymd_opt(
            i32::from(date.year),
            u32::from(date.month),
            u32::from(date.day),
        )
        .and_then(|date| date.and_hms_opt(0, 0, 0));
        if let Some(midnight) = midnight {
            return Ok(midnight);
        }
    }

    Err(Refusal::invalid(format!("invalid timestamp {text:?}")))
}

/// Parse a wire duration the way the Python `TimeDelta` does, the Pydantic grammar
/// first, ISO 8601 intervals and clock forms, then the suffix grammar.
///
/// Every record filter duration is non-negative on the wire, so a negative one
/// refuses here.
fn parse_duration(text: &str) -> Result<Duration, Refusal> {
    let invalid = || Refusal::invalid(format!("invalid duration {text:?}"));

    if let Ok(duration) =
        speedate::Duration::parse_bytes_with_config(text.as_bytes(), &speedate_config())
    {
        if !duration.positive {
            return Err(invalid());
        }

        return Ok(Duration::days(i64::from(duration.day))
            + Duration::seconds(i64::from(duration.second))
            + Duration::microseconds(i64::from(duration.microsecond)));
    }

    // The suffix grammar, a bare number meaning seconds.
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

    if number.is_empty() {
        return Err(invalid());
    }

    let value: f64 = number.parse().map_err(|_| invalid())?;
    if !value.is_finite() || value < 0.0 {
        return Err(invalid());
    }

    Ok(Duration::microseconds((value * scale).round() as i64))
}

/// One bucket membership condition, the timestamp landing among each bucket's kept
/// timestamps.
#[expect(clippy::too_many_arguments)]
fn bucket_condition(
    table: RecordTable,
    key: &'static str,
    origin: NaiveDateTime,
    width: i64,
    start: Option<NaiveDateTime>,
    end: Option<NaiveDateTime>,
    select: SubsampleSelect,
    dialect: SqlDialect,
) -> SimpleExpr {
    let kept = match select {
        SubsampleSelect::First => Func::cust(Alias::new("MIN")).arg(Expr::col(Alias::new(key))),
        SubsampleSelect::Last => Func::cust(Alias::new("MAX")).arg(Expr::col(Alias::new(key))),
    };

    let mut buckets = Query::select();
    buckets.expr(kept).from(Alias::new(table.name()));
    if let Some(start) = start {
        buckets.and_where(Expr::col(Alias::new(key)).gte(timestamp_value(start, dialect)));
    }

    if let Some(end) = end {
        buckets.and_where(Expr::col(Alias::new(key)).lt(timestamp_value(end, dialect)));
    }

    buckets.add_group_by([bucket_expression(key, origin, width, dialect)]);
    Expr::col(Alias::new(key)).in_subquery(buckets)
}

/// Which bucket a row's timestamp falls in, an expression constant across a bucket.
///
/// PostgreSQL brings `date_bin`. The SQLite family has no equivalent and Turso cannot
/// register one, so the bucket index computes from the stored text, whole seconds and
/// microseconds kept apart as integers so a timestamp on a bucket boundary stays in
/// its own bucket. The fraction reads from the text because the SQLite family parses
/// only milliseconds, and padding covers a value stored without one.
fn bucket_expression(
    key: &'static str,
    origin: NaiveDateTime,
    width: i64,
    dialect: SqlDialect,
) -> SimpleExpr {
    match dialect {
        SqlDialect::Postgres => Expr::cust_with_expr(
            format!(
                "date_bin(INTERVAL '{width} microseconds', $1, TIMESTAMP '{}')",
                Parameter::timestamp_text(&origin)
            ),
            Expr::col(Alias::new(key)),
        ),
        SqlDialect::SqliteText => {
            let origin_seconds = origin.and_utc().timestamp();
            let origin_microseconds = i64::from(origin.and_utc().timestamp_subsec_micros());
            Expr::cust_with_exprs(
                format!(
                    "CAST(((unixepoch(?) - {origin_seconds}) * 1000000 + \
                     (CAST(substr(substr(?, 20) || '.000000', 2, 6) AS INTEGER) - \
                     {origin_microseconds})) / {width} AS INTEGER)"
                ),
                [
                    Expr::col(Alias::new(key)).into(),
                    Expr::col(Alias::new(key)).into(),
                ],
            )
        }
    }
}

/// Integer division rounding half to even, the way Python divides a `timedelta`.
fn divide_rounding_half_even(total: i64, divisor: i64) -> i64 {
    let quotient = total.div_euclid(divisor);
    let remainder = total.rem_euclid(divisor);
    let doubled = remainder * 2;
    if doubled > divisor || (doubled == divisor && quotient % 2 != 0) {
        quotient + 1
    } else {
        quotient
    }
}

/// The hour or minute of the stored timestamp, per backend.
///
/// The SQLite family reads it from the stored text, PostgreSQL from the native
/// timestamp pinned to UTC, the way the Python layer writes both.
fn clock_part(key: &'static str, part: &str, format: &str, dialect: SqlDialect) -> SimpleExpr {
    match dialect {
        SqlDialect::SqliteText => Func::cust(Alias::new("strftime"))
            .arg(format)
            .arg(Expr::col(Alias::new(key)))
            .cast_as(Alias::new("INTEGER")),
        SqlDialect::Postgres => Expr::cust_with_expr(
            format!("date_part('{part}', $1 AT TIME ZONE 'UTC')"),
            Expr::col(Alias::new(key)),
        ),
    }
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
pub(crate) fn like_escape(text: &str) -> String {
    text.replace('%', "^%").replace('_', "^_")
}

/// Escape the characters `GLOB` treats as wildcards, so the text matches literally.
///
/// `GLOB` has no `ESCAPE` clause, a metacharacter is made literal by wrapping it in a
/// character class instead. The `[` goes first so the classes the later replacements
/// introduce stay intact.
pub(crate) fn glob_escape(text: &str) -> String {
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

/// Whether a text value matches one pattern by an operation's kind.
fn text_matches(value: &str, kind: OperationKind, pattern: &str) -> bool {
    match kind {
        OperationKind::Contains => value.contains(pattern),
        OperationKind::Prefix => value.starts_with(pattern),
        OperationKind::Suffix => value.ends_with(pattern),
    }
}

/// Whether a bytes value matches one pattern by an operation's kind, whole bytes.
fn bytes_match(value: &[u8], kind: OperationKind, pattern: &[u8]) -> bool {
    match kind {
        OperationKind::Contains => {
            pattern.is_empty() || value.windows(pattern.len()).any(|window| window == pattern)
        }
        OperationKind::Prefix => value.starts_with(pattern),
        OperationKind::Suffix => value.ends_with(pattern),
    }
}

/// A record's timestamp parsed from its serialized RFC 3339 form.
fn record_timestamp(text: Option<&str>) -> Option<NaiveDateTime> {
    let text = text?;
    if let Ok(aware) = chrono::DateTime::parse_from_rfc3339(text) {
        return Some(aware.naive_utc());
    }

    None
}

/// All conditions joined with `AND`, as one expression.
fn all_of(conditions: Vec<SimpleExpr>) -> SimpleExpr {
    conditions
        .into_iter()
        .reduce(|combined, condition| combined.and(condition))
        .expect("grouping requires at least one condition")
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
    fn only_the_particle_class_still_delegates() {
        assert_eq!(
            RecordFilter::parse(RecordTable::Particles, &pairs(&[("class", "a.b:C")])),
            Err(Refusal::Delegated),
        );
        assert!(matches!(
            RecordFilter::parse(RecordTable::Messages, &pairs(&[("class", "a.b:C")])),
            Err(Refusal::Invalid(_)),
        ));
        for table in [
            RecordTable::Messages,
            RecordTable::Alerts,
            RecordTable::Logs,
        ] {
            assert!(RecordFilter::delegated_keys(table).is_empty());
        }
    }

    #[test]
    fn subsampling_compiles_grouped_bucket_subqueries() {
        let filter = RecordFilter::parse(
            RecordTable::Particles,
            &pairs(&[("subsample_every", "1m"), ("after", "2026-07-30T00:00:00Z")]),
        )
        .unwrap();
        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains("\"timestamp\" IN (SELECT MIN(\"timestamp\") FROM \"particles\""),
            "{sql}"
        );
        assert!(sql.contains("GROUP BY CAST"), "{sql}");
        assert!(sql.contains("/ 60000000 AS INTEGER)"), "{sql}");

        let sql = filter
            .statement(SqlDialect::Postgres)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(
            sql.contains("GROUP BY date_bin(INTERVAL '60000000 microseconds', \"timestamp\", TIMESTAMP '2026-07-30 00:00:00.000000')"),
            "{sql}"
        );

        // A count-based subsample derives its width from the bounded range.
        let counted = RecordFilter::parse(
            RecordTable::Particles,
            &pairs(&[
                ("subsample", "60"),
                ("after", "2026-07-30T00:00:00Z"),
                ("before", "2026-07-30T01:00:00Z"),
                ("subsample_select", "last"),
            ]),
        )
        .unwrap();
        let sql = counted
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("SELECT MAX(\"timestamp\")"), "{sql}");
        assert!(sql.contains("/ 60000000 AS INTEGER)"), "{sql}");
    }

    #[test]
    fn count_subsampling_requires_a_bounded_range() {
        for (rejected, message) in [
            (pairs(&[("subsample", "10")]), "Start and end time"),
            (
                pairs(&[("subsample", "10"), ("after", "2026-07-30")]),
                "End time",
            ),
            (
                pairs(&[("subsample", "10"), ("before", "2026-07-30")]),
                "Start time",
            ),
        ] {
            match RecordFilter::parse(RecordTable::Particles, &rejected) {
                Err(Refusal::Invalid(text)) => {
                    assert!(text.starts_with(message), "{rejected:?}: {text}");
                }
                other => panic!("{rejected:?} parsed as {other:?}"),
            }
        }

        // A timespan bounds both sides at once.
        assert!(
            RecordFilter::parse(
                RecordTable::Particles,
                &pairs(&[("subsample", "10"), ("timespan", "1h")]),
            )
            .is_ok()
        );
    }

    #[test]
    fn division_rounds_half_to_even_like_python() {
        assert_eq!(divide_rounding_half_even(7, 2), 4);
        assert_eq!(divide_rounding_half_even(5, 2), 2);
        assert_eq!(divide_rounding_half_even(9, 3), 3);
        assert_eq!(divide_rounding_half_even(10, 4), 2);
        assert_eq!(divide_rounding_half_even(14, 4), 4);
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
            pairs(&[("address", "@a,@b")]),
            pairs(&[("address", "@a|")]),
            pairs(&[("root", "sensor")]),
            pairs(&[("root", "@a"), ("root", "@b")]),
            pairs(&[("after", "yesterday")]),
            pairs(&[("timespan", "-PT5S")]),
            pairs(&[("timespan", "0")]),
            pairs(&[("timespan", "week")]),
            pairs(&[("after_hour", "25")]),
            pairs(&[("before_minute", "61")]),
            pairs(&[("after_hour", "9"), ("after_hour", "10")]),
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
    fn boolean_groups_compile_the_matching_semantics() {
        // An or subfilter's conditions hold together as one term.
        let filter = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[
                ("or", "{connection: network, direction: receive}"),
                ("connection", "serial"),
            ]),
        )
        .unwrap();
        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains(
                "WHERE \"connection\" = 'serial' OR (\"connection\" = 'network' AND \
                 \"direction\" = 'receive')"
            ),
            "{sql}"
        );

        // An empty or subfilter matches everything.
        let open = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("or", "{}"), ("connection", "serial")]),
        )
        .unwrap();
        let sql = open
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains("WHERE \"connection\" = 'serial' OR TRUE"),
            "{sql}"
        );

        // And subfilters extend the node's conditions.
        let both = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("and", "[{connection: serial}, {direction: send}]")]),
        )
        .unwrap();
        let sql = both
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains("WHERE \"connection\" = 'serial' AND \"direction\" = 'send'"),
            "{sql}"
        );

        // Groups nest recursively.
        let nested = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("or", "{and: [{connection: network}, {direction: send}]}")]),
        )
        .unwrap();
        let sql = nested
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains("WHERE \"connection\" = 'network' AND \"direction\" = 'send'"),
            "{sql}"
        );
    }

    #[test]
    fn and_subfilters_hoist_their_query_controls() {
        let filter = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[
                ("limit", "3"),
                ("and", "{limit: 5, offset: 2, order: \"timestamp:desc\"}"),
            ]),
        )
        .unwrap();
        assert_eq!(filter.limit(), Some(3));

        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains("ORDER BY \"timestamp\" DESC LIMIT 3 OFFSET 2"),
            "{sql}"
        );

        let tighter = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("limit", "5"), ("and", "{limit: 3}")]),
        )
        .unwrap();
        assert_eq!(tighter.limit(), Some(3));
    }

    #[test]
    fn or_subfilters_refuse_query_controls() {
        for rejected in ["{limit: 5}", "{offset: 2}", "{order: timestamp}"] {
            let outcome = RecordFilter::parse(RecordTable::Messages, &pairs(&[("or", rejected)]));
            assert!(matches!(outcome, Err(Refusal::Invalid(_))), "{rejected}");
        }

        // A nested and hoists into the or subfilter, which then refuses.
        let hoisted = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("or", "{and: {limit: 5}}")]),
        );
        assert!(matches!(hoisted, Err(Refusal::Invalid(_))));
    }

    #[test]
    fn malformed_groups_refuse_as_invalid() {
        for rejected in ["not: [valid", "5", "[5]", "abc", "{connection: {a: b}}"] {
            let outcome = RecordFilter::parse(RecordTable::Messages, &pairs(&[("or", rejected)]));
            assert!(matches!(outcome, Err(Refusal::Invalid(_))), "{rejected}");
        }
    }

    #[test]
    fn address_selectors_compile_with_roots() {
        let filter = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("address", ":children"), ("root", "@deck")]),
        )
        .unwrap();
        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("GLOB '@deck.*'"), "{sql}");

        let filter = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("address", "@a"), ("address", "@b:descendants")]),
        )
        .unwrap();
        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains("\"address\" = '@a' OR (\"address\" GLOB '@b.*')"),
            "{sql}"
        );
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
    fn durations_parse_both_wire_grammars() {
        assert_eq!(parse_duration("5s"), Ok(Duration::seconds(5)));
        assert_eq!(parse_duration("1.5 h"), Ok(Duration::seconds(5400)));
        assert_eq!(parse_duration("100ms"), Ok(Duration::milliseconds(100)));
        assert_eq!(parse_duration("7d"), Ok(Duration::days(7)));
        assert_eq!(parse_duration("90"), Ok(Duration::seconds(90)));
        assert_eq!(parse_duration("90.5"), Ok(Duration::milliseconds(90500)));
        assert_eq!(parse_duration("PT5S"), Ok(Duration::seconds(5)));
        assert_eq!(parse_duration("P1DT2H"), Ok(Duration::hours(26)));
        assert_eq!(parse_duration("01:02:03"), Ok(Duration::seconds(3723)));
        assert!(matches!(parse_duration("-5s"), Err(Refusal::Invalid(_))));
        assert!(matches!(parse_duration("-PT5S"), Err(Refusal::Invalid(_))));
        assert!(matches!(parse_duration("week"), Err(Refusal::Invalid(_))));
    }

    #[test]
    fn timestamps_parse_the_python_wire_grammar() {
        let expected = chrono::NaiveDate::from_ymd_opt(2026, 7, 30)
            .unwrap()
            .and_hms_opt(12, 30, 0)
            .unwrap();
        assert_eq!(parse_timestamp("2026-07-30T12:30:00"), Ok(expected));
        assert_eq!(parse_timestamp("2026-07-30 12:30:00Z"), Ok(expected));
        assert_eq!(parse_timestamp("2026-07-30T14:30:00+02:00"), Ok(expected));

        let midnight = chrono::NaiveDate::from_ymd_opt(2026, 7, 30)
            .unwrap()
            .and_hms_opt(0, 0, 0)
            .unwrap();
        assert_eq!(parse_timestamp("2026-07-30"), Ok(midnight));

        let epoch = parse_timestamp("1722340000").unwrap();
        assert_eq!(epoch.and_utc().timestamp(), 1722340000);
        assert!(matches!(
            parse_timestamp("yesterday"),
            Err(Refusal::Invalid(_))
        ));
    }

    #[test]
    fn clock_windows_compile_per_backend() {
        let filter = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("after_hour", "9"), ("before_hour", "17")]),
        )
        .unwrap();
        let sql = filter
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains(
                "CAST(strftime('%H', \"timestamp\") AS INTEGER) >= 9 AND \
                 CAST(strftime('%H', \"timestamp\") AS INTEGER) < 17"
            ),
            "{sql}"
        );

        let sql = filter
            .statement(SqlDialect::Postgres)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(
            sql.contains("(date_part('hour', \"timestamp\" AT TIME ZONE 'UTC')) >= 9"),
            "{sql}"
        );

        // A wrapped window joins its bounds with OR instead.
        let wrapped = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("after_minute", "45"), ("before_minute", "10")]),
        )
        .unwrap();
        let sql = wrapped
            .statement(SqlDialect::SqliteText)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains(
                "CAST(strftime('%M', \"timestamp\") AS INTEGER) >= 45 OR \
                 CAST(strftime('%M', \"timestamp\") AS INTEGER) < 10"
            ),
            "{sql}"
        );
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
