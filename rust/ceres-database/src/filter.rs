//! The native record filter compiler, the single authority on the record filter
//! language.
//!
//! A filter parses from wire query pairs or its serialized JSON form into a tree.
//! The root carries the query controls (ordering and pagination), each node carries
//! matching conditions, and boolean groups nest as child nodes. The native server and
//! CLI execute the compiled statements on their own store, and the Python query layer
//! executes the same compiled SQL on its session so there is no second compiler to
//! drift.
//!
//! Parsing refuses in two ways. [`Refusal::Invalid`] carries a wire-invalid value,
//! which the native paths delegate to Python so the canonical Pydantic envelope
//! reports it. [`Refusal::Delegated`] marks the one construct with no native form, a
//! particle's `class`, a Python import the filter model resolves to its type
//! discriminator before parsing so only the wire paths refuse it.
//!
//! The admissible keys are generated, never written out. Each entity's
//! [`Filterable`](ceres_entities::Filterable) derive reads its struct at compile
//! time, and every field's family brings its operators, window operators for a
//! timestamp, ordered bounds for a level, equality for text and enum fields. The
//! cross-backend parity suite pins the compiled statements and the matcher to the
//! query layer's results on every backend.

use ceres_entities::{
    Address, Entities, FieldFamily, FilterField, FilterValues, Level, OperationKind, Records,
    latin1,
};
use chrono::{Duration, NaiveDateTime, SubsecRound, Utc};
use sea_query::{
    Alias, Asterisk, BinOper, DeleteStatement, Expr, ExprTrait, Func, LikeExpr, Order, Query,
    SelectStatement, SimpleExpr, UpdateStatement, Value,
};
use uuid::Uuid;
use yaml_serde::Value as Yaml;

use crate::credentials::normalize_email;
use crate::entities::EntityTable;
use crate::records::{Computed, RecordTable, Schema, Shape};
use crate::selector::{AddressSelector, valid_address};
use crate::store::Parameter;

/// How values render into the statement, per backend family.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum SqlDialect {
    /// SQLite and Turso, where timestamps, UUIDs, and JSON payloads bind and compare
    /// as their stored text.
    SqliteText,
    /// Native driver types throughout.
    Postgres,
}

/// Why a filter refused to parse natively.
///
/// The native wire paths hand both cases to the Python operation, an invalid value so
/// the canonical validation envelope reports it, and a delegated construct so the
/// filter model resolves it. The Python query layer raises instead because its own
/// validation already rejected anything invalid.
#[derive(Clone, Debug, PartialEq)]
pub enum Refusal {
    /// The construct sits outside what the compiler serves so the request delegates.
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
    /// A key matching a shape of a column rather than its value.
    Computed(Computed),
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
    /// One boolean, which its family takes in place of a set.
    Boolean(bool),
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
    /// Computed predicates, each with whether the shape must hold or must not.
    computed: Vec<(Computed, bool)>,
    /// Whether the node can match at all. An explicitly empty value list matches
    /// nothing, like the Python layer's empty `IN`.
    impossible: bool,
    /// Subfilter groups. An `and` node's conditions hold together with this node's,
    /// an `or` node matches on its own.
    and_children: Vec<FilterNode>,
    or_children: Vec<FilterNode>,
}

/// A parsed filter, the tree's root plus the query controls.
///
/// Every statement builds from the schema alone so the record and entity filters are
/// each this core plus a table enum, and one compiler serves both.
#[derive(Clone, Debug, PartialEq)]
struct FilterCore {
    schema: Schema,
    node: FilterNode,
    order: Vec<OrderTerm>,
    limit: Option<u64>,
    offset: Option<u64>,
}

impl FilterCore {
    /// Parse query pairs into a filter, refusing what cannot compile natively.
    ///
    /// Repeated keys collect into lists, matching how the Python layer folds ordered
    /// pairs before validating.
    fn parse(schema: Schema, pairs: &[(String, String)]) -> Result<Self, Refusal> {
        let mut parsed = Parsed::default();
        for (key, value) in pairs {
            parsed.apply(schema, key, &WireValue::Text(value))?;
        }

        let Parsed {
            node,
            order,
            limit,
            offset,
            ..
        } = parsed.finish()?;
        Ok(Self {
            schema,
            node,
            order,
            limit,
            offset,
        })
    }

    /// Parse a filter from its serialized JSON form, the Python filter model's dump.
    ///
    /// JSON is a YAML subset so this reads through the same parser the subfilter
    /// values use.
    fn from_json(schema: Schema, text: &str) -> Result<Self, Refusal> {
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
        } = Parsed::from_yaml(schema, &mapping)?;
        Ok(Self {
            schema,
            node,
            order,
            limit,
            offset,
        })
    }

    /// Cap the limit, defaulting an absent one, the way the route's `Limit` wrapper
    /// does. A limit above the cap is a validation error.
    fn with_limit_cap(mut self, cap: u64) -> Result<Self, Refusal> {
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

    /// Compile to SQL and its bound parameters, in the dialect's placeholder style.
    ///
    /// The parameters arrive in placeholder order, ready for a driver-level execute,
    /// `?` for the SQLite family and `$n` for PostgreSQL.
    pub fn compiled(
        &self,
        dialect: SqlDialect,
        count: bool,
        now: Option<NaiveDateTime>,
    ) -> (String, Vec<Value>) {
        let statement = if count {
            self.count_statement(dialect, now)
        } else {
            self.statement(dialect, now)
        };
        build(statement, dialect)
    }

    /// Compile the existence check to SQL and its bound parameters.
    pub fn exists_compiled(
        &self,
        dialect: SqlDialect,
        now: Option<NaiveDateTime>,
    ) -> (String, Vec<Value>) {
        build(self.exists_statement(dialect, now), dialect)
    }

    /// Compile the delete to SQL and its bound parameters.
    ///
    /// `returning` fetches the deleted rows because a second query could no
    /// longer find them.
    pub fn delete_compiled(
        &self,
        dialect: SqlDialect,
        returning: bool,
        now: Option<NaiveDateTime>,
    ) -> (String, Vec<Value>) {
        let mut statement = self.delete_statement(dialect, now);
        if returning {
            statement.returning_all();
        }

        build(statement, dialect)
    }

    /// Compile an update to SQL and its bound parameters, for one set clause object.
    ///
    /// The object is the same JSON an `update` command carries. Each value encodes
    /// into the form its column stores, and a refusal names the offending key and the
    /// form it expected.
    pub fn update_compiled(
        &self,
        dialect: SqlDialect,
        set: &serde_json::Map<String, serde_json::Value>,
        returning: bool,
        now: Option<NaiveDateTime>,
    ) -> Result<(String, Vec<Value>), Refusal> {
        let set_clauses = self
            .schema
            .set_clauses(set, dialect)
            .map_err(Refusal::Invalid)?;
        let mut statement = self.update_statement(dialect, &set_clauses, now);
        if returning {
            statement.returning_all();
        }

        Ok(build(statement, dialect))
    }

    /// The combined `WHERE` conditions rendered as inline SQL, `None` when the filter
    /// is unconditional.
    ///
    /// The text embeds into a statement the Python session builds so values render
    /// as literals rather than binds.
    pub fn where_sql(&self, dialect: SqlDialect, now: Option<NaiveDateTime>) -> Option<String> {
        let now = resolve_now(now);
        let conditions = self.node.combined_conditions(self.schema, dialect, now);
        if conditions.is_empty() {
            return None;
        }

        let mut statement = Query::select();
        statement.expr(all_of(conditions));
        Some(rendered_after(&statement, dialect, "SELECT "))
    }

    /// The `ORDER BY` terms rendered as inline SQL, `None` when the table brings no
    /// default ordering.
    pub fn order_sql(&self, dialect: SqlDialect) -> Option<String> {
        let terms = self.order_terms();
        if terms.is_empty() {
            return None;
        }

        let mut statement = Query::select();
        statement.expr(Expr::val(1));
        for term in terms {
            order_by(&mut statement, term, dialect);
        }

        Some(rendered_after(&statement, dialect, "SELECT 1 ORDER BY "))
    }

    /// Whether one serialized record matches this filter, like the Python filter's
    /// `matches`.
    ///
    /// Query controls and subsampling do not apply because this reads a single
    /// record the way live stream filtering does. Age-relative conditions compare
    /// against the moment of the call.
    pub fn matches(&self, record_json: &str, now: Option<NaiveDateTime>) -> Result<bool, String> {
        let fields: std::collections::HashMap<&str, &serde_json::value::RawValue> =
            serde_json::from_str(record_json)
                .map_err(|error| format!("unreadable record: {error}"))?;
        let now = resolve_now(now);
        Ok(self.node.matches(self.schema, &fields, now))
    }

    /// Build the listing statement, matching the Python query layer's semantics.
    pub fn statement(&self, dialect: SqlDialect, now: Option<NaiveDateTime>) -> SelectStatement {
        let now = resolve_now(now);
        let mut statement = Query::select();
        statement
            .column(Asterisk)
            .from(Alias::new(self.schema.name));
        for condition in self.node.combined_conditions(self.schema, dialect, now) {
            statement.and_where(condition);
        }

        for term in self.order_terms() {
            order_by(&mut statement, term, dialect);
        }

        self.page(&mut statement, dialect);
        statement
    }

    /// Apply the filter's limit and offset to a statement.
    ///
    /// SQLite refuses a bare `OFFSET` so an unlimited query carrying one gets the
    /// same unreachable limit SQLAlchemy emits.
    fn page(&self, statement: &mut SelectStatement, dialect: SqlDialect) {
        if let Some(limit) = self.limit {
            statement.limit(limit);
        } else if self.offset.is_some() && dialect == SqlDialect::SqliteText {
            statement.limit(i64::MAX as u64);
        }

        if let Some(offset) = self.offset {
            statement.offset(offset);
        }
    }

    /// Build the count statement.
    ///
    /// A limit or offset bounds the count itself, matching the Python layer, which
    /// counts over the paged primary-key subquery in that case.
    pub fn count_statement(
        &self,
        dialect: SqlDialect,
        now: Option<NaiveDateTime>,
    ) -> SelectStatement {
        let now = resolve_now(now);
        if self.limit.is_none() && self.offset.is_none() {
            let mut statement = Query::select();
            statement
                .expr(Expr::cust("COUNT(*)"))
                .from(Alias::new(self.schema.name));
            for condition in self.node.combined_conditions(self.schema, dialect, now) {
                statement.and_where(condition);
            }

            return statement;
        }

        let mut inner = Query::select();
        inner.from(Alias::new(self.schema.name));
        for column in self.schema.key {
            inner.column(Alias::new(*column));
        }

        for condition in self.node.combined_conditions(self.schema, dialect, now) {
            inner.and_where(condition);
        }

        for term in self.order_terms() {
            order_by(&mut inner, term, dialect);
        }

        self.page(&mut inner, dialect);

        let mut statement = Query::select();
        statement
            .expr(Expr::cust("COUNT(*)"))
            .from_subquery(inner, Alias::new("matched"));
        statement
    }

    /// Build the existence statement, `SELECT EXISTS (...)`.
    ///
    /// Ordering never changes whether a row exists, and the Python layer ignores it here
    /// too so the inner query carries only the conditions and the page bounds.
    pub fn exists_statement(
        &self,
        dialect: SqlDialect,
        now: Option<NaiveDateTime>,
    ) -> SelectStatement {
        let now = resolve_now(now);
        let mut inner = Query::select();
        inner.column(Asterisk).from(Alias::new(self.schema.name));
        for condition in self.node.combined_conditions(self.schema, dialect, now) {
            inner.and_where(condition);
        }

        self.page(&mut inner, dialect);

        let mut statement = Query::select();
        statement.expr(Expr::exists(inner));
        statement
    }

    /// The primary keys the filter's page selects, `None` when there is no page and
    /// conditions can apply in place.
    fn paged_keys(&self, dialect: SqlDialect, now: NaiveDateTime) -> Option<SelectStatement> {
        if self.limit.is_none() && self.offset.is_none() {
            return None;
        }

        let mut keys = Query::select();
        keys.from(Alias::new(self.schema.name));
        for column in self.schema.key {
            keys.column(Alias::new(*column));
        }

        for condition in self.node.combined_conditions(self.schema, dialect, now) {
            keys.and_where(condition);
        }

        for term in self.order_terms() {
            order_by(&mut keys, term, dialect);
        }

        self.page(&mut keys, dialect);
        Some(keys)
    }

    /// The primary key as one expression, a bare column for a single key and a row
    /// value for a composite one.
    ///
    /// This is what a paged write narrows on, and the Python layer builds the same two
    /// forms from the row's primary key constraint.
    fn key_expression(&self) -> SimpleExpr {
        match self.schema.key {
            [column] => Expr::col(Alias::new(*column)).into(),
            columns => Expr::tuple(
                columns
                    .iter()
                    .map(|column| Expr::col(Alias::new(*column)).into()),
            )
            .into(),
        }
    }

    /// Build the delete statement, matching the Python query layer's semantics.
    ///
    /// Without a page the conditions apply in place. With one the statement deletes
    /// the keys its ordered page names because a `DELETE` carries neither ordering
    /// nor pagination of its own.
    fn delete_statement(&self, dialect: SqlDialect, now: Option<NaiveDateTime>) -> DeleteStatement {
        let now = resolve_now(now);
        let mut statement = Query::delete();
        statement.from_table(Alias::new(self.schema.name));
        match self.paged_keys(dialect, now) {
            Some(keys) => {
                statement.and_where(self.key_expression().in_subquery(keys));
            }
            None => {
                for condition in self.node.combined_conditions(self.schema, dialect, now) {
                    statement.and_where(condition);
                }
            }
        }

        statement
    }

    /// Build the update statement for the encoded set clauses.
    fn update_statement(
        &self,
        dialect: SqlDialect,
        set_clauses: &[crate::set::SetClause],
        now: Option<NaiveDateTime>,
    ) -> UpdateStatement {
        let now = resolve_now(now);
        let mut statement = Query::update();
        statement.table(Alias::new(self.schema.name));
        for clause in set_clauses {
            statement.value(Alias::new(clause.column), clause.value.clone());
        }

        match self.paged_keys(dialect, now) {
            Some(keys) => {
                statement.and_where(self.key_expression().in_subquery(keys));
            }
            None => {
                for condition in self.node.combined_conditions(self.schema, dialect, now) {
                    statement.and_where(condition);
                }
            }
        }

        statement
    }

    /// The order terms, defaulting to the table's own order columns.
    ///
    /// Every default order column must be a filterable field, pinned by the schema
    /// tests because an unresolved one would silently list unordered.
    fn order_terms(&self) -> Vec<OrderTerm> {
        if !self.order.is_empty() {
            return self.order.clone();
        }

        self.schema
            .order
            .iter()
            .filter_map(|column| {
                self.schema
                    .fields
                    .iter()
                    .find(|field| field.key == *column)
                    .map(|field| OrderTerm {
                        field,
                        ascending: true,
                    })
            })
            .collect()
    }
}

/// A table a filter can query.
///
/// The record and entity tables both implement this so [`Filter`] is written once
/// and [`RecordFilter`] and [`EntityFilter`] are the same type over different tables.
pub trait Tabled: Copy {
    /// The batch a result set over this table decodes into.
    type Batch;

    /// What the compiler needs to know about the table.
    fn schema(self) -> Schema;

    /// An empty batch of this table's kind, what a query that cannot match returns.
    fn empty(self) -> Self::Batch;
}

impl Tabled for RecordTable {
    type Batch = Records;

    fn schema(self) -> Schema {
        Self::schema(&self)
    }

    fn empty(self) -> Records {
        Self::empty(&self)
    }
}

impl Tabled for EntityTable {
    type Batch = Entities;

    fn schema(self) -> Schema {
        Self::schema(&self)
    }

    fn empty(self) -> Entities {
        Self::empty(&self)
    }
}

/// A parsed filter, the compiled core plus the table it names.
#[derive(Clone, Debug, PartialEq)]
pub struct Filter<T: Tabled> {
    table: T,
    filter: FilterCore,
}

/// A parsed record filter, the compiled core plus the record table it names.
pub type RecordFilter = Filter<RecordTable>;

/// A parsed entity filter, the compiled core plus the entity table it names.
///
/// The entity filter language is a strict subset of the record one, both descending
/// from the same Pydantic base so this is the same core over a schema with fewer
/// field families.
pub type EntityFilter = Filter<EntityTable>;

impl<T: Tabled> Filter<T> {
    /// The field and query filter keys the native compiler serves for a table.
    ///
    /// Generated from the entity's field families, never written out. Equality
    /// for every native family, each field's operation filters, the operators a
    /// family brings, the table's computed predicates, and the query keys.
    pub fn supported_keys(table: T) -> Vec<&'static str> {
        table.schema().supported_keys()
    }

    /// The filter keys the compiler knowingly delegates for a table.
    ///
    /// These are Python's structural query filters plus its Python-only constructs.
    /// The classification test holds this list plus the supported one to exactly
    /// what the Pydantic models declare so a new filter field cannot ship
    /// unclassified.
    pub fn delegated_keys(table: T) -> Vec<&'static str> {
        table.schema().delegated.to_vec()
    }

    /// Every filter key this table serves, with the argument form its family
    /// gives it.
    ///
    /// A parser builds from this rather than from a list of names so it cannot
    /// disagree with the compiler about whether a key is a bare flag or takes a
    /// value.
    pub fn keys(table: T) -> Vec<FilterKey> {
        table.schema().filter_keys()
    }

    /// Every column a create may name, with the argument form its family gives
    /// it.
    ///
    /// A write names columns rather than filter keys, which is a different
    /// surface. A user's password hash is a column no filter exposes, and a
    /// filter's operations and windows name no column at all.
    pub fn columns(table: T) -> Vec<FilterKey> {
        table.schema().column_keys()
    }

    /// Parse query pairs into a filter, refusing what cannot compile natively.
    pub fn parse(table: T, pairs: &[(String, String)]) -> Result<Self, Refusal> {
        Ok(Self {
            table,
            filter: FilterCore::parse(table.schema(), pairs)?,
        })
    }

    /// Parse a filter from its serialized JSON form, the Python filter model's
    /// dump.
    pub fn from_json(table: T, text: &str) -> Result<Self, Refusal> {
        Ok(Self {
            table,
            filter: FilterCore::from_json(table.schema(), text)?,
        })
    }

    /// The table this filter queries.
    pub fn table(&self) -> T {
        self.table
    }

    /// The parsed limit, which callers cap before executing on the server.
    pub fn limit(&self) -> Option<u64> {
        self.filter.limit
    }

    /// The filter's offset, `None` when unset.
    pub fn offset(&self) -> Option<u64> {
        self.filter.offset
    }

    /// Cap the limit, defaulting an absent one, the way the route's `Limit`
    /// wrapper does. A limit above the cap is a validation error.
    pub fn with_limit_cap(self, cap: u64) -> Result<Self, Refusal> {
        Ok(Self {
            table: self.table,
            filter: self.filter.with_limit_cap(cap)?,
        })
    }

    /// Build the listing statement, matching the Python query layer's semantics.
    pub fn statement(&self, dialect: SqlDialect, now: Option<NaiveDateTime>) -> SelectStatement {
        self.filter.statement(dialect, now)
    }

    /// Build the count statement.
    pub fn count_statement(
        &self,
        dialect: SqlDialect,
        now: Option<NaiveDateTime>,
    ) -> SelectStatement {
        self.filter.count_statement(dialect, now)
    }

    /// Build the existence statement, `SELECT EXISTS (...)`.
    pub fn exists_statement(
        &self,
        dialect: SqlDialect,
        now: Option<NaiveDateTime>,
    ) -> SelectStatement {
        self.filter.exists_statement(dialect, now)
    }

    /// Build the delete statement, matching the Python query layer's semantics.
    pub fn delete_statement(
        &self,
        dialect: SqlDialect,
        now: Option<NaiveDateTime>,
    ) -> DeleteStatement {
        self.filter.delete_statement(dialect, now)
    }

    /// Compile to SQL and its bound parameters, in the dialect's placeholder
    /// style.
    ///
    /// The parameters arrive in placeholder order, ready for a driver-level
    /// execute, `?` for the SQLite family and `$n` for PostgreSQL.
    pub fn compiled(
        &self,
        dialect: SqlDialect,
        count: bool,
        now: Option<NaiveDateTime>,
    ) -> (String, Vec<Value>) {
        self.filter.compiled(dialect, count, now)
    }

    /// Compile the existence check to SQL and its bound parameters.
    pub fn exists_compiled(
        &self,
        dialect: SqlDialect,
        now: Option<NaiveDateTime>,
    ) -> (String, Vec<Value>) {
        self.filter.exists_compiled(dialect, now)
    }

    /// Compile the delete to SQL and its bound parameters.
    pub fn delete_compiled(
        &self,
        dialect: SqlDialect,
        returning: bool,
        now: Option<NaiveDateTime>,
    ) -> (String, Vec<Value>) {
        self.filter.delete_compiled(dialect, returning, now)
    }

    /// Compile an update to SQL and its bound parameters, for one set clause
    /// object.
    pub fn update_compiled(
        &self,
        dialect: SqlDialect,
        set: &serde_json::Map<String, serde_json::Value>,
        returning: bool,
        now: Option<NaiveDateTime>,
    ) -> Result<(String, Vec<Value>), Refusal> {
        self.filter.update_compiled(dialect, set, returning, now)
    }

    /// The combined `WHERE` conditions rendered as inline SQL, `None` when the
    /// filter is unconditional.
    pub fn where_sql(&self, dialect: SqlDialect, now: Option<NaiveDateTime>) -> Option<String> {
        self.filter.where_sql(dialect, now)
    }

    /// The `ORDER BY` terms rendered as inline SQL, `None` when the table brings
    /// no default ordering.
    pub fn order_sql(&self, dialect: SqlDialect) -> Option<String> {
        self.filter.order_sql(dialect)
    }

    /// Whether one serialized row matches this filter, like the Python filter's
    /// `matches`.
    pub fn matches(&self, record_json: &str, now: Option<NaiveDateTime>) -> Result<bool, String> {
        self.filter.matches(record_json, now)
    }

    /// Build the update statement for the encoded set clauses.
    pub(crate) fn update_statement(
        &self,
        dialect: SqlDialect,
        set_clauses: &[crate::set::SetClause],
        now: Option<NaiveDateTime>,
    ) -> UpdateStatement {
        self.filter.update_statement(dialect, set_clauses, now)
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

    /// The value as one whole, for a field that compares on a serialized structure.
    ///
    /// Plain wire text is already the text a value column stores, and a YAML value
    /// serializes to the same JSON the Python side writes so a mapping and a
    /// sequence both cross whole rather than as the scalars inside them.
    fn whole(&self, key: &str) -> Result<String, Refusal> {
        match self {
            Self::Text(text) => json_text(text),
            Self::Yaml(value) => serde_json::to_string(value)
                .map_err(|_| Refusal::invalid(format!("invalid {key} value"))),
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

/// The instant age-relative conditions compare against, the caller's clock when given
/// and the wall clock otherwise.
///
/// A caller passes its own clock so a Python session under a faked or frozen time
/// stays authoritative. Truncating to microseconds matches Python's `datetime`
/// resolution so arithmetic and rendering agree on both sides. Each statement
/// resolves this once and shares it across every node so `min_age` and `max_age` in
/// the same filter cannot straddle a tick.
fn resolve_now(now: Option<NaiveDateTime>) -> NaiveDateTime {
    now.unwrap_or_else(|| Utc::now().naive_utc())
        .trunc_subsecs(6)
}

/// One YAML scalar in the text form the wire parsers read, `None` for the rest.
fn yaml_scalar(value: &Yaml) -> Option<String> {
    match value {
        Yaml::String(text) => Some(text.clone()),
        // Only a field whose value can be null reaches here holding one, and its stored
        // text is the JSON spelling.
        Yaml::Null => Some("null".to_string()),
        Yaml::Number(number) => Some(number.to_string()),
        // A filter model dumps a boolean field as a JSON boolean rather than as the text
        // a query string carries, and both spell it the same way.
        Yaml::Bool(held) => Some(held.to_string()),
        _ => None,
    }
}

/// Parse one wire YAML value the way the Python `FromYAML` reads it, empty text
/// reading as null.
fn parse_yaml(text: &str) -> Result<Yaml, Refusal> {
    if text.trim().is_empty() {
        return Ok(Yaml::Null);
    }

    yaml_serde::from_str(text).map_err(|_| Refusal::invalid(format!("invalid YAML {text:?}")))
}

/// A filter node mid-parse, its query controls and subfilter groups still attached.
///
/// A subfilter can carry `order`, `limit`, and `offset`, which hoist into its parent
/// under the Python model's rules rather than compiling as conditions so they ride
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
    fn apply(&mut self, table: Schema, key: &str, value: &WireValue) -> Result<(), Refusal> {
        match table.resolve(key)? {
            KeyRole::Equality(field) => {
                // A value column compares on the whole serialized value so a list is
                // one value rather than a set of alternatives.
                if field.family == FieldFamily::JsonValue {
                    self.node.push_equality(field, &value.whole(key)?)?;
                    return Ok(());
                }

                // A scalar field takes one value rather than a set so a list is a
                // validation error the Python model owns.
                let scalars = value.scalars(key)?;
                if field.family.scalar() && scalars.len() != 1 {
                    return Err(Refusal::invalid(format!("{key} takes one value")));
                }

                if scalars.is_empty() {
                    self.node.impossible = true;
                }

                for scalar in scalars {
                    self.node.push_equality(field, &scalar)?;
                }
            }
            // A computed key takes one boolean, holding the shape or its opposite.
            KeyRole::Computed(predicate) => {
                let scalar = value.scalar(key)?;
                let sense = match scalar.as_str() {
                    "true" | "True" => true,
                    "false" | "False" => false,
                    other => {
                        return Err(Refusal::invalid(format!("invalid boolean {other:?}")));
                    }
                };
                self.node.computed.push((predicate, sense));
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
                let children = table.group_children(value)?;
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
                    self.order.push(table.parse_order(&scalar)?);
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
    fn from_yaml(table: Schema, mapping: &yaml_serde::Mapping) -> Result<Self, Refusal> {
        let mut parsed = Self::default();
        for (key, value) in mapping {
            let Some(key) = key.as_str() else {
                return Err(Refusal::invalid("subfilter keys must be strings"));
            };

            // A null value leaves its field unset, like the Python models, except on
            // a field that can store null, where `null` is a real value to filter on.
            if matches!(value, Yaml::Null) && !table.nullable(key) {
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
            // The filter model types this field as a validated address so the value
            // normalizes before comparing. One the normalizer cannot handle delegates
            // because comparing it unnormalized would silently miss its row.
            FieldFamily::Email => match normalize_email(value) {
                Some(normalized) => Values::Texts(vec![normalized]),
                None => return Err(Refusal::Delegated),
            },
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
            FieldFamily::Bytes => Values::Bytes(vec![latin1::encode(value)]),
            // A JSON field carries no equality key, only its operation filters, so its
            // own key never resolves here.
            FieldFamily::Json => return Err(Refusal::Delegated),
            // A boolean takes one value so naming the key twice is a validation
            // error, as for any scalar field in the Python models.
            FieldFamily::Boolean => {
                let parsed = match value {
                    "true" | "True" => true,
                    "false" | "False" => false,
                    _ => return Err(Refusal::invalid(format!("invalid boolean {value:?}"))),
                };
                Values::Boolean(parsed)
            }
            // A value compares on the serialized text the column stores so the wire
            // text parses as YAML and re-serializes into that form.
            FieldFamily::JsonValue => Values::Texts(vec![json_text(value)?]),
            // A plain address compares whole, outside the selector grammar.
            FieldFamily::PlainAddress => {
                Address::parse(value).map_err(Refusal::Invalid)?;
                Values::Texts(vec![value.to_string()])
            }
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
                // A scalar field takes one value so a second is a validation error
                // rather than the set a repeated key builds elsewhere.
                (Values::Boolean(_), _) => {
                    return Err(Refusal::invalid(format!("{} takes one value", field.key)));
                }
                _ => return Err(Refusal::Delegated),
            },
        }

        Ok(())
    }

    /// Add one operation filter value. Repeated values collect into a list, like the
    /// Python layer's folding.
    fn push_operation(&mut self, field: &'static FilterField, kind: OperationKind, value: &str) {
        let parsed = match field.family {
            FieldFamily::Bytes => Values::Bytes(vec![latin1::encode(value)]),
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
        table: Schema,
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
        table: Schema,
        fields: &std::collections::HashMap<&str, &serde_json::value::RawValue>,
        now: NaiveDateTime,
    ) -> bool {
        if self.impossible {
            return false;
        }

        for (predicate, sense) in &self.computed {
            let held = fields
                .get(predicate.column)
                .copied()
                .is_some_and(|raw| holds(predicate.shape, raw));
            if held != *sense {
                return false;
            }
        }

        for field in table.fields {
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
                        .is_some_and(|text| patterns.contains(&latin1::encode(text))),
                    // A value column compares on the serialized text of whatever it
                    // holds so the raw wire JSON is the thing to compare.
                    (Values::Texts(texts), FieldFamily::JsonValue) => raw
                        .and_then(|raw| serde_json::from_str::<serde_json::Value>(raw.get()).ok())
                        .map(|value| value.to_string())
                        .is_some_and(|held| texts.contains(&held)),
                    (Values::Texts(texts), _) => text
                        .as_deref()
                        .is_some_and(|text| texts.iter().any(|candidate| candidate == text)),
                    (Values::Boolean(wanted), _) => raw
                        .and_then(|raw| serde_json::from_str::<bool>(raw.get()).ok())
                        .is_some_and(|held| held == *wanted),
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
                            // A case-folding operation lowers both sides, the way the
                            // Python matcher does before comparing.
                            let subject = fold(subject, operation.insensitive);
                            patterns.iter().any(|pattern| {
                                text_matches(
                                    &subject,
                                    held_values.kind,
                                    &fold(pattern, operation.insensitive),
                                )
                            })
                        })
                    }
                    Values::Bytes(patterns) => text.as_deref().is_some_and(|text| {
                        let value = latin1::encode(text);
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
                        && position.is_none_or(|position| position < minimum)
                    {
                        return false;
                    }

                    if let Some(maximum) = self.max_level
                        && position.is_none_or(|position| position > maximum)
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

        let (span_start, span_end) = self.timespan_bounds(now);
        if span_start.is_some_and(|start| stamp < start) {
            return false;
        }

        if span_end.is_some_and(|end| stamp >= end) {
            return false;
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
            let Some((minimum, maximum, contiguous)) = clock_window(after, before, span) else {
                continue;
            };

            let within_minimum = value >= minimum;
            let within_maximum = value < maximum;
            let held = if contiguous {
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

    /// The bounds a `timespan` adds, anchored after, before, or at the clock, in that
    /// precedence.
    ///
    /// The matcher, the compiler, and the subsampling bounds all read the anchor rule
    /// from here so the three cannot disagree about what a timespan means.
    fn timespan_bounds(
        &self,
        now: NaiveDateTime,
    ) -> (Option<NaiveDateTime>, Option<NaiveDateTime>) {
        let Some(timespan) = self.timespan else {
            return (None, None);
        };

        if let Some(after) = self.after {
            (None, Some(after + timespan))
        } else if let Some(before) = self.before {
            (Some(before - timespan), None)
        } else {
            (Some(now - timespan), Some(now))
        }
    }

    /// This node's conditions joined with its subfilter groups', collapsing to one
    /// condition when an `or` group is present.
    ///
    /// An `and` node's conditions extend this node's. An `or` node matches on its
    /// own, its conditions grouped to hold together, and one with no conditions
    /// matches everything.
    fn combined_conditions(
        &self,
        table: Schema,
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
        table: Schema,
        dialect: SqlDialect,
        now: NaiveDateTime,
    ) -> Vec<SimpleExpr> {
        let mut conditions = Vec::new();
        if self.impossible {
            conditions.push(Expr::value(false));
        }

        for (predicate, sense) in &self.computed {
            let condition = shape_condition(*predicate, dialect);
            conditions.push(if *sense { condition } else { condition.not() });
        }

        for field in table.fields {
            let column = Expr::col(Alias::new(field.key));
            if let Some(values) = self.values_of(field) {
                conditions.push(match values {
                    // A value column holds JSON, and the comparison is against its
                    // text so the column casts before it compares, matching the cast
                    // the Python filter applies.
                    Values::Texts(texts) if field.family == FieldFamily::JsonValue => match_values(
                        Expr::expr(column.clone().cast_as(Alias::new("TEXT"))),
                        texts.iter().cloned().map(Value::from),
                    ),
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
                    Values::Boolean(wanted) => column.clone().eq(*wanted),
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

        let (span_start, span_end) = self.timespan_bounds(now);
        if let Some(start) = span_start {
            conditions.push(column.clone().gte(timestamp_value(start, dialect)));
        }

        if let Some(end) = span_end {
            conditions.push(column.clone().lt(timestamp_value(end, dialect)));
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

        let (span_start, span_end) = self.timespan_bounds(now);
        starts.extend(span_start);
        ends.extend(span_end);

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
    /// origin and keep the first or last timestamp of each so the condition is one
    /// grouped subquery per control.
    fn subsample_conditions(
        &self,
        conditions: &mut Vec<SimpleExpr>,
        table: Schema,
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
            conditions
                .push(table.bucket_condition(key, origin, width, start, end, select, dialect));
        }

        if let Some(count) = self.subsample {
            // Validation guaranteed both bounds.
            let (Some(start), Some(end)) = (start, end) else {
                return;
            };
            let total = (end - start).num_microseconds().unwrap_or(0);
            let width = divide_rounding_half_even(total, count.max(1) as i64).max(1);
            conditions.push(table.bucket_condition(
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
    /// A window whose lower bound exceeds its upper wraps around midnight so the two
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
            let Some((minimum, maximum, contiguous)) = clock_window(after, before, span) else {
                continue;
            };

            let value = clock_part(key, part, format, dialect);
            let within_minimum = value.clone().gte(minimum);
            let within_maximum = value.lt(maximum);
            if contiguous {
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
                    // A JSON payload matches against its serialized text so the
                    // column casts before the comparison, like the Python layer's.
                    let column = Expr::col(Alias::new(field.key));
                    let subject = if field.family == FieldFamily::Json {
                        column.cast_as(Alias::new("TEXT"))
                    } else {
                        column.into()
                    };
                    match_text_patterns(
                        subject,
                        held.kind,
                        patterns,
                        dialect,
                        operation.insensitive,
                    )
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

/// One filter key and the argument form that carries it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FilterKey {
    pub key: &'static str,
    /// Whether the key is a bare flag or takes a value, which its family decides.
    pub arity: Arity,
    /// What the key does, which a generated help text is written from.
    pub role: Role,
    /// The field the key filters on, for the keys that name one.
    ///
    /// An operation or window key does not always carry its field's name, a log's
    /// `contains` searches its content and a timestamp's `after` names no field.
    pub field: Option<&'static str>,
}

/// How a filter key arrives on the command line.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Arity {
    /// A `--key` and `--no-key` pair carrying no value of its own, the form a scalar
    /// boolean takes.
    Flag,
    /// A `--key value` pair, repeatable where the field folds a list.
    Value,
}

/// What a filter key does, which decides the help text generated for it.
///
/// Carried here rather than inferred from the key's spelling because guessing the
/// role back from a name would let a help text describe the wrong thing.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Role {
    /// Compare a field whole, several values matching any of them.
    Equality,
    /// Match within a field's content.
    Operation(OperationKind),
    /// The address that relative selector segments resolve against.
    Root,
    /// Bound a timestamp, absolutely or by age.
    Window(Window),
    /// Bound an ordered field, currently only a log level.
    Bound,
    /// Hold a shape of a column rather than a value of it.
    Computed,
    /// Order, limit, or offset the result rather than narrow it.
    Query,
    /// Combine whole subfilters.
    Group,
}

/// Which way a window bounds a timestamp.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Window {
    /// An absolute bound, `after` and `before`.
    Absolute,
    /// A bound relative to now, `max_age` and `min_age`.
    Age,
    /// A span, `timespan`.
    Span,
    /// A bound on the time of day rather than the date.
    Clock,
    /// Thin the result to one row per interval.
    Subsample,
}

impl Schema {
    /// Whether naming `None` for a field filters for null rather than not filtering.
    ///
    /// A value column stores its JSON text, `null` included, so the null is one of the
    /// values it compares against. Every other family reads an absent value as no
    /// filter.
    fn nullable(self, key: &str) -> bool {
        self.fields
            .iter()
            .any(|field| field.key == key && field.family == FieldFamily::JsonValue)
    }

    /// The subfilters one `or` or `and` wire value carries.
    ///
    /// A plain text value parses as YAML first. The result is one subfilter mapping, a
    /// sequence of them, or nothing, and a sequence element may itself be YAML text of
    /// one mapping, the way the Python `FromYAML` layers read it.
    fn group_children(self, value: &WireValue) -> Result<Vec<Parsed>, Refusal> {
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
                Yaml::Mapping(mapping) => Parsed::from_yaml(self, mapping),
                _ => Err(Refusal::invalid("a subfilter must be a mapping")),
            }
        };

        match value {
            Yaml::Null => Ok(Vec::new()),
            Yaml::Sequence(elements) => elements.iter().map(one).collect(),
            other => Ok(vec![one(other)?]),
        }
    }

    /// The field and query filter keys the native compiler serves for a table.
    ///
    /// Generated from the entity's field families, never written out. Equality for
    /// every native family, each field's operation filters, the window operators a
    /// timestamp brings, the ordered bounds a level brings, the table's computed
    /// predicates, and the query keys every table shares.
    pub(crate) fn supported_keys(self) -> Vec<&'static str> {
        self.filter_keys().into_iter().map(|key| key.key).collect()
    }

    /// Every filter key a table serves, with the argument form its family gives it.
    ///
    /// Generated from the entity's fields rather than written out so a parser built
    /// from this cannot disagree with the compiler about what a key is or how it
    /// arrives. A flat list of names would drop the arity a parser needs.
    pub(crate) fn filter_keys(self) -> Vec<FilterKey> {
        let keyed = |key, arity, role, field| FilterKey {
            key,
            arity,
            role,
            field,
        };

        let mut keys = Vec::new();
        for field in self.fields {
            // A field's own key lists before the operations that search within it
            // because a reader looking for a field wants the whole-value comparison
            // first. A field whose own key is delegated still brings its operations,
            // which is how an email filters on its parts without comparing whole.
            if field.family.native() && !self.delegated.contains(&field.key) {
                let arity = if field.family.scalar() {
                    Arity::Flag
                } else {
                    Arity::Value
                };
                keys.push(keyed(field.key, arity, Role::Equality, Some(field.key)));
            }

            // An operation matches within a field's content so it always takes a
            // value and names the field it searches.
            keys.extend(field.operations.iter().map(|operation| {
                keyed(
                    operation.key,
                    Arity::Value,
                    Role::Operation(operation.kind),
                    Some(field.key),
                )
            }));

            if !field.family.native() || self.delegated.contains(&field.key) {
                continue;
            }

            let window = |key, kind| keyed(key, Arity::Value, Role::Window(kind), Some(field.key));
            match field.family {
                FieldFamily::Address => {
                    keys.push(keyed("root", Arity::Value, Role::Root, Some(field.key)));
                }
                FieldFamily::Timestamp => {
                    keys.extend(["after", "before"].map(|key| window(key, Window::Absolute)));
                    keys.push(window("timespan", Window::Span));
                    keys.extend(["max_age", "min_age"].map(|key| window(key, Window::Age)));
                    keys.extend(
                        ["after_hour", "before_hour", "after_minute", "before_minute"]
                            .map(|key| window(key, Window::Clock)),
                    );
                    keys.extend(
                        ["subsample_every", "subsample", "subsample_select"]
                            .map(|key| window(key, Window::Subsample)),
                    );
                }
                FieldFamily::Level => keys.extend(
                    bound_keys(field)
                        .map(|key| keyed(key, Arity::Value, Role::Bound, Some(field.key))),
                ),
                _ => {}
            }
        }

        // A computed predicate answers yes or no so it is a flag like any other
        // boolean.
        keys.extend(self.computed.iter().map(|predicate| {
            keyed(
                predicate.key,
                Arity::Flag,
                Role::Computed,
                Some(predicate.column),
            )
        }));
        keys.extend(
            ["order", "limit", "offset"].map(|key| keyed(key, Arity::Value, Role::Query, None)),
        );
        keys.extend(["or", "and"].map(|key| keyed(key, Arity::Value, Role::Group, None)));
        keys
    }

    /// Every column a create may name, with the argument form its family gives it.
    ///
    /// Generated from the entity's columns for the same reason the filter keys are, so
    /// the parser and the writer cannot disagree about what a create accepts.
    pub(crate) fn column_keys(self) -> Vec<FilterKey> {
        self.columns
            .iter()
            .map(|field| FilterKey {
                key: field.key,
                arity: if field.family.scalar() {
                    Arity::Flag
                } else {
                    Arity::Value
                },
                // A column names itself, and a write assigns it whole rather than matching
                // within it.
                role: Role::Equality,
                field: Some(field.key),
            })
            .collect()
    }

    /// Resolve what one wire key means for a table, from the entity's field families.
    fn resolve(self, key: &str) -> Result<KeyRole, Refusal> {
        match key {
            "order" => return Ok(KeyRole::Order),
            "limit" => return Ok(KeyRole::Limit),
            "offset" => return Ok(KeyRole::Offset),
            "or" => return Ok(KeyRole::Group(GroupOp::Or)),
            "and" => return Ok(KeyRole::Group(GroupOp::And)),
            _ => {}
        }

        // The delegated list wins over the field families because a key can name a
        // field the compiler otherwise serves and still belong to Python, as an
        // email's equality does.
        if self.delegated.contains(&key) {
            return Err(Refusal::Delegated);
        }

        for predicate in self.computed {
            if predicate.key == key {
                return Ok(KeyRole::Computed(*predicate));
            }
        }

        for field in self.fields {
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

        // The Python filter models forbid extra fields so an unrecognized key is a
        // validation error rather than a delegated construct.
        Err(Refusal::invalid(format!("unknown filter key {key:?}")))
    }

    /// Parse an order value, `field`, `field:asc`, or `field:desc` over the entity's
    /// filterable fields.
    fn parse_order(self, text: &str) -> Result<OrderTerm, Refusal> {
        let (base, ascending) = match text.split_once(':') {
            None => (text, true),
            Some((base, "asc")) => (base, true),
            Some((base, "desc")) => (base, false),
            Some(_) => return Err(Refusal::invalid(format!("invalid order {text:?}"))),
        };

        let field = self
            .fields
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

    /// One bucket membership condition, the timestamp landing among each bucket's kept
    /// timestamps.
    #[expect(clippy::too_many_arguments)]
    fn bucket_condition(
        self,
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
        buckets.expr(kept).from(Alias::new(self.name));
        if let Some(start) = start {
            buckets.and_where(Expr::col(Alias::new(key)).gte(timestamp_value(start, dialect)));
        }

        if let Some(end) = end {
            buckets.and_where(Expr::col(Alias::new(key)).lt(timestamp_value(end, dialect)));
        }

        buckets.add_group_by([bucket_expression(key, origin, width, dialect)]);
        Expr::col(Alias::new(key)).in_subquery(buckets)
    }
}

/// The bound keys a level field brings, `min_` and `max_` prefixed on its key.
fn bound_keys(field: &FilterField) -> [&'static str; 2] {
    // The record level fields are all named `level` today, and the keys have to be
    // `'static` for the classification lists so the prefix join is spelled out here
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

/// The compact JSON text a value column stores, parsed from the wire's YAML form.
///
/// The Python filter compares `to_json(self.value)` against the column cast to text, so
/// the comparison is on serialized form and a number, a string, and a structure all
/// compare by the same rule.
fn json_text(value: &str) -> Result<String, Refusal> {
    let parsed: serde_json::Value = yaml_serde::from_str(value)
        .map_err(|_| Refusal::invalid(format!("invalid value {value:?}")))?;
    Ok(parsed.to_string())
}

/// Parse a wire timestamp on the grammar the Python `DateTime` accepts, ISO forms,
/// epoch numbers, and bare dates, aware values normalizing to UTC and naive ones read
/// as UTC.
pub(crate) fn parse_timestamp(text: &str) -> Result<NaiveDateTime, Refusal> {
    let config = speedate::DateTimeConfig {
        time_config: speedate_config(),
        ..Default::default()
    };
    if let Ok(datetime) = speedate::DateTime::parse_str_with_config(text, &config) {
        // Whole seconds and the fraction recombine from the same epoch so a
        // pre-epoch value lands on the instant its fields name rather than one
        // truncated toward zero.
        let microseconds =
            datetime.timestamp_tz() * 1_000_000 + i64::from(datetime.time.microsecond);
        if let Some(parsed) = chrono::DateTime::from_timestamp_micros(microseconds) {
            return Ok(parsed.naive_utc());
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
/// Every record filter duration is non-negative on the wire so a negative one
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

/// Which bucket a row's timestamp falls in, an expression constant across a bucket.
///
/// PostgreSQL brings `date_bin`. The SQLite family has no equivalent and Turso cannot
/// register one so the bucket index computes from the stored text, whole seconds and
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
                "date_bin(INTERVAL '{width} microseconds', $1, TIMESTAMPTZ '{}+00')",
                Parameter::timestamp_text(&origin)
            ),
            Expr::col(Alias::new(key)),
        ),
        SqlDialect::SqliteText => {
            let origin_seconds = origin.and_utc().timestamp();
            let origin_microseconds = i64::from(origin.and_utc().timestamp_subsec_micros());
            // The division floors over reals, matching the floored true division the
            // Python layer compiled so a record older than the origin still lands in
            // the bucket below rather than truncating toward zero.
            Expr::cust_with_exprs(
                format!(
                    "CAST(floor(((unixepoch(?) - {origin_seconds}) * 1000000.0 + \
                     (CAST(substr(substr(?, 20) || '.000000', 2, 6) AS INTEGER) - \
                     {origin_microseconds})) / {width}) AS INTEGER)"
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

/// One time-of-day window's bounds, and whether the window is contiguous.
///
/// `None` when neither side is bounded. A lower bound above the upper wraps around
/// midnight so its two comparisons join with `OR` instead of `AND`. The matcher and
/// the compiler both read the defaulting and the wrap rule from here so the two
/// cannot disagree about what a window means.
fn clock_window(after: Option<u32>, before: Option<u32>, span: u32) -> Option<(u32, u32, bool)> {
    if after.is_none() && before.is_none() {
        return None;
    }

    let minimum = after.unwrap_or(0);
    let maximum = before.unwrap_or(span);
    Some((minimum, maximum, minimum <= maximum))
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

/// Escape the `LIKE` wildcards `%` and `_` with `^`, like the Python layer.
pub(crate) fn like_escape(text: &str) -> String {
    text.replace('%', "^%").replace('_', "^_")
}

/// Escape the characters `GLOB` treats as wildcards so the text matches literally.
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
/// Mirrors the Python `tokenize_bytes` and the PostgreSQL `ceres_tokenize_bytes`
/// function its trigram index uses, the trailing space marking the last byte's token
/// boundary.
fn tokenize_bytes(value: &[u8]) -> String {
    use std::fmt::Write;

    let mut text = String::with_capacity(value.len() * 3);
    for byte in value {
        write!(text, "{byte:02x} ").expect("writing to a string never fails");
    }

    text
}

/// Whether one record's wire value holds a computed predicate's shape.
fn holds(shape: Shape, raw: &serde_json::value::RawValue) -> bool {
    match shape {
        Shape::Internal => serde_json::from_str::<String>(raw.get())
            .is_ok_and(|name| name.starts_with("__") && name.ends_with("__")),
        Shape::Literal(wanted) => {
            serde_json::from_str::<String>(raw.get()).is_ok_and(|held| held == wanted)
        }
        Shape::Present => raw.get() != "null",
    }
}

/// Compile a computed predicate's shape into the condition that holds it.
fn shape_condition(predicate: Computed, dialect: SqlDialect) -> SimpleExpr {
    let column = || SimpleExpr::from(Expr::col(Alias::new(predicate.column)));
    match predicate.shape {
        // An internal name both opens and closes with a double underscore, which is two
        // pattern matches rather than one, each escaped by its backend's own rules.
        Shape::Internal => {
            let marker = ["__".to_string()];
            match_text_patterns(column(), OperationKind::Prefix, &marker, dialect, false).and(
                match_text_patterns(column(), OperationKind::Suffix, &marker, dialect, false),
            )
        }
        Shape::Literal(wanted) => Expr::col(Alias::new(predicate.column)).eq(wanted),
        Shape::Present => Expr::col(Alias::new(predicate.column)).is_not_null(),
    }
}

/// Match a text subject against patterns, `GLOB` on the SQLite family and an escaped
/// `LIKE` on PostgreSQL.
///
/// When every pattern is empty the whole match is true, even for a null subject,
/// matching the answer the Python query layer's SQL builder gives.
fn match_text_patterns(
    subject: SimpleExpr,
    kind: OperationKind,
    patterns: &[String],
    dialect: SqlDialect,
    insensitive: bool,
) -> SimpleExpr {
    if patterns.iter().all(|pattern| pattern.is_empty()) {
        return Expr::value(true);
    }

    patterns
        .iter()
        .map(|pattern| {
            let escaped = with_wildcards(like_escape(pattern), kind, '%');
            match (dialect, insensitive) {
                // Case folding is `ILIKE` on PostgreSQL and a pair of `lower` calls
                // on the SQLite family, matching what SQLAlchemy renders. Lowering in
                // SQL keeps the backend's ASCII-only fold rather than Rust's Unicode
                // one. The placeholder in a custom expression is the dialect's own.
                (SqlDialect::SqliteText, true) => Expr::cust_with_exprs(
                    "lower(?) LIKE lower(?) ESCAPE '^'",
                    [subject.clone(), Expr::val(escaped).into()],
                ),
                (SqlDialect::Postgres, true) => Expr::cust_with_exprs(
                    "$1 ILIKE $2 ESCAPE '^'",
                    [subject.clone(), Expr::val(escaped).into()],
                ),
                // A case-sensitive match on the SQLite family is `GLOB` because `LIKE`
                // there folds ASCII case whether or not it was asked to.
                (SqlDialect::SqliteText, false) => {
                    let pattern = with_wildcards(glob_escape(pattern), kind, '*');
                    subject
                        .clone()
                        .binary(BinOper::Custom("GLOB"), Expr::val(pattern))
                }
                (SqlDialect::Postgres, false) => {
                    subject.clone().like(LikeExpr::new(escaped).escape('^'))
                }
            }
        })
        .reduce(|combined, condition| combined.or(condition))
        .expect("patterns are never empty here")
}

/// Match a bytes column against patterns, whole-byte comparisons on the SQLite family
/// and the tokenized hex its trigram index covers on PostgreSQL.
///
/// An empty pattern is contained in, starts, and ends every value so it matches any
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

/// Lower a value for a case-folding comparison, leaving it alone for a plain one.
///
/// Python's `str.lower` folds by Unicode so the in-memory comparison does too, which
/// is deliberately not the ASCII fold the backends apply in SQL.
fn fold(text: &str, insensitive: bool) -> std::borrow::Cow<'_, str> {
    if insensitive {
        std::borrow::Cow::Owned(text.to_lowercase())
    } else {
        std::borrow::Cow::Borrowed(text)
    }
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

/// Render a statement in the dialect's placeholder style, `?` for the SQLite family
/// and `$n` for PostgreSQL.
fn build<S: sea_query::QueryStatementBuilder>(
    statement: S,
    dialect: SqlDialect,
) -> (String, Vec<Value>) {
    let (sql, values) = match dialect {
        SqlDialect::SqliteText => statement.build_any(&sea_query::SqliteQueryBuilder),
        SqlDialect::Postgres => statement.build_any(&sea_query::PostgresQueryBuilder),
    };
    (sql, values.0)
}

/// Render a statement in a dialect and return what follows a fixed prefix.
fn rendered_after(statement: &SelectStatement, dialect: SqlDialect, prefix: &str) -> String {
    let rendered = match dialect {
        SqlDialect::SqliteText => statement.to_string(sea_query::SqliteQueryBuilder),
        SqlDialect::Postgres => statement.to_string(sea_query::PostgresQueryBuilder),
    };
    rendered
        .strip_prefix(prefix)
        .expect("the statement renders with its fixed prefix")
        .to_string()
}

/// All conditions joined with `AND`, as one expression.
fn all_of(conditions: Vec<SimpleExpr>) -> SimpleExpr {
    conditions
        .into_iter()
        .reduce(|combined, condition| combined.and(condition))
        .expect("grouping requires at least one condition")
}

/// An equality for one value, an `IN` for several.
fn match_values(column: Expr, values: impl Iterator<Item = Value> + Clone) -> SimpleExpr {
    let mut peek = values.clone();
    let first = peek.next();
    match (first, peek.next()) {
        (Some(value), None) => column.eq(value),
        _ => column.is_in(values),
    }
}

/// A UUID in its bound form, stored text on the SQLite family.
pub(crate) fn id_value(id: Uuid, dialect: SqlDialect) -> Value {
    match dialect {
        SqlDialect::SqliteText => Value::from(id.to_string()),
        SqlDialect::Postgres => Value::from(id),
    }
}

/// A timestamp in its bound form, the stored text on the SQLite family.
///
/// PostgreSQL takes the aware UTC form, its timestamp columns carry a zone and a
/// naive value would read in the session's own.
fn timestamp_value(timestamp: NaiveDateTime, dialect: SqlDialect) -> Value {
    match dialect {
        SqlDialect::SqliteText => Value::from(Parameter::timestamp_text(&timestamp)),
        SqlDialect::Postgres => Value::from(timestamp.and_utc()),
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
        FieldFamily::Address
            | FieldFamily::PlainAddress
            | FieldFamily::Text
            | FieldFamily::Values(_)
            | FieldFamily::Level
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

    /// One entity filter's listing SQL in the SQLite dialect.
    fn entity_sql(table: EntityTable, entries: &[(&str, &str)]) -> String {
        EntityFilter::parse(table, &pairs(entries))
            .expect("the filter parses")
            .statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder)
    }

    #[test]
    fn every_entity_lists_in_its_own_default_order() {
        // An unresolved default order column would list unordered, which the Python
        // path never does so each table's rendering is pinned here.
        let ordering = |table| {
            entity_sql(table, &[])
                .split_once(" ORDER BY ")
                .map(|(_, tail)| tail.to_string())
                .unwrap_or_default()
        };

        assert_eq!(ordering(EntityTable::Users), "\"username\" ASC");
        assert_eq!(
            ordering(EntityTable::Variables),
            "\"address\" ASC, \"name\" ASC"
        );
        // A setting sorts by name alone, though its key is the owner and the name.
        assert_eq!(ordering(EntityTable::Settings), "\"name\" ASC");
        assert_eq!(ordering(EntityTable::Workspaces), "\"name\" ASC");
    }

    #[test]
    fn one_statement_resolves_the_clock_once() {
        // A caller's clock reaches every age-relative condition in the statement, and
        // reaches all of them as the same instant. Resolving per condition would let
        // `min_age` and `max_age` straddle a tick and render a window that excludes a
        // row sitting exactly on the boundary.
        let now = NaiveDateTime::parse_from_str("2026-07-31 12:00:00", "%Y-%m-%d %H:%M:%S")
            .expect("the instant parses");
        let sql = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("max_age", "PT1H"), ("min_age", "PT1H")]),
        )
        .expect("the filter parses")
        .statement(SqlDialect::SqliteText, Some(now))
        .to_string(SqliteQueryBuilder);

        // Both bounds land on the same hour-old instant so the pair reads as one point
        // rather than as a window whose ends were measured a tick apart.
        assert!(
            sql.contains("\"timestamp\" > '2026-07-31 11:00:00.000000'")
                && sql.contains("\"timestamp\" <= '2026-07-31 11:00:00.000000'"),
            "{sql}"
        );
    }

    #[test]
    fn a_composite_key_narrows_a_paged_write_by_row_value() {
        // Without a page the conditions apply in place, whatever the key looks like.
        let plain = EntityFilter::parse(EntityTable::Variables, &pairs(&[("name", "x")]))
            .unwrap()
            .delete_statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert_eq!(
            plain, "DELETE FROM \"variables\" WHERE \"name\" = 'x'",
            "{plain}"
        );

        // With one, the whole key tuple has to name the page, the way the Python layer
        // builds `tuple_(*pk).in_(...)` for a composite primary key.
        let paged = EntityFilter::parse(EntityTable::Variables, &pairs(&[("limit", "2")]))
            .unwrap()
            .delete_statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(
            paged.starts_with(
                "DELETE FROM \"variables\" WHERE (\"address\", \"name\") IN \
                 (SELECT \"address\", \"name\" FROM \"variables\""
            ),
            "{paged}"
        );

        // A single key column stays a plain membership test.
        let single = EntityFilter::parse(EntityTable::Users, &pairs(&[("limit", "2")]))
            .unwrap()
            .delete_statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(
            single.starts_with("DELETE FROM \"users\" WHERE \"id\" IN (SELECT \"id\""),
            "{single}"
        );
    }

    #[test]
    fn an_email_filters_by_its_parts_and_delegates_whole() {
        // Equality normalizes the value first because the filter model types the field
        // as a validated address and so compares a normalized one against the column.
        let sql = entity_sql(EntityTable::Users, &[("email", "Ada@Example.COM")]);
        assert!(sql.contains("\"email\" = 'ada@example.com'"), "{sql}");
        assert!(EntityFilter::supported_keys(EntityTable::Users).contains(&"email"));
        assert!(EntityFilter::supported_keys(EntityTable::Users).contains(&"email_contains"));

        // An address the normalizer does not understand delegates, rather than comparing
        // unnormalized and quietly missing the row it names.
        assert_eq!(
            EntityFilter::parse(EntityTable::Users, &pairs(&[("email", "a@localhost")])),
            Err(Refusal::Delegated)
        );

        // The operations fold case, which on the SQLite family is a pair of `lower`
        // calls and on PostgreSQL is `ILIKE`, matching what SQLAlchemy renders.
        let sql = entity_sql(EntityTable::Users, &[("email_prefix", "Ada")]);
        assert!(
            sql.contains("lower(\"email\") LIKE lower('Ada%') ESCAPE '^'"),
            "{sql}"
        );

        let postgres = EntityFilter::parse(EntityTable::Users, &pairs(&[("email_prefix", "Ada")]))
            .unwrap()
            .statement(SqlDialect::Postgres, None)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(
            postgres.contains("\"email\" ILIKE 'Ada%' ESCAPE '^'"),
            "{postgres}"
        );

        // A username does not fold so it keeps the case-sensitive rendering every
        // record text field has.
        let sql = entity_sql(EntityTable::Users, &[("username_prefix", "Ada")]);
        assert!(sql.contains("\"username\" GLOB 'Ada*'"), "{sql}");
    }

    #[test]
    fn the_entity_grammar_is_the_record_one_without_the_record_families() {
        // A variable's address takes the selector grammar and its root, and its name
        // takes the text operations.
        let keys = EntityFilter::supported_keys(EntityTable::Variables);
        for key in [
            "address",
            "root",
            "name",
            "name_contains",
            "value",
            "internal",
        ] {
            assert!(keys.contains(&key), "{key} missing from {keys:?}");
        }

        // No entity carries a timestamp or a level so the window, clock, subsample,
        // and bound operators never reach their surface.
        for key in ["after", "before_hour", "subsample_every", "min_level"] {
            assert!(!keys.contains(&key), "{key} present in {keys:?}");
            assert!(matches!(
                EntityFilter::parse(EntityTable::Variables, &pairs(&[(key, "1")])),
                Err(Refusal::Invalid(_))
            ));
        }

        // The query keys every table shares are here, subfilter groups included.
        for key in ["order", "limit", "offset", "or", "and"] {
            assert!(keys.contains(&key), "{key} missing from {keys:?}");
        }
    }

    #[test]
    fn computed_predicates_match_a_shape_of_a_column() {
        // An internal variable's name both opens and closes with a double underscore.
        let sql = entity_sql(EntityTable::Variables, &[("internal", "true")]);
        assert!(
            sql.contains("\"name\" GLOB '__*'") && sql.contains("\"name\" GLOB '*__'"),
            "{sql}"
        );

        // A workspace is placed on the engine when its scope is the engine's address,
        // and owned when it names an owner at all.
        let sql = entity_sql(EntityTable::Workspaces, &[("placed_on_engine", "false")]);
        assert!(sql.contains("\"scope\" = '~'"), "{sql}");
        let sql = entity_sql(EntityTable::Workspaces, &[("owned", "true")]);
        assert!(sql.contains("\"owner_id\" IS NOT NULL"), "{sql}");
    }

    #[test]
    fn a_boolean_takes_one_value_and_a_json_value_compares_as_text() {
        // The Python models type these as scalars so a list is a validation error
        // rather than a set membership test.
        assert!(matches!(
            EntityFilter::parse(
                EntityTable::Users,
                &pairs(&[("admin", "true"), ("admin", "false")])
            ),
            Err(Refusal::Invalid(_))
        ));
        let sql = entity_sql(EntityTable::Users, &[("admin", "true")]);
        assert!(sql.contains("\"admin\" = TRUE"), "{sql}");

        // A variable's value compares on the column's text so a number compares as a
        // number rather than as its quoted form.
        let sql = entity_sql(EntityTable::Variables, &[("value", "5")]);
        assert!(sql.contains("CAST(\"value\" AS TEXT) = '5'"), "{sql}");

        // A null is a value like any other, selecting the rows that hold one.
        let sql = entity_sql(EntityTable::Variables, &[("value", "null")]);
        assert!(sql.contains("CAST(\"value\" AS TEXT) = 'null'"), "{sql}");
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
            .statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains("\"timestamp\" IN (SELECT MIN(\"timestamp\") FROM \"particles\""),
            "{sql}"
        );
        assert!(sql.contains("GROUP BY CAST"), "{sql}");
        assert!(sql.contains("/ 60000000) AS INTEGER)"), "{sql}");

        let sql = filter
            .statement(SqlDialect::Postgres, None)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(
            sql.contains("GROUP BY date_bin(INTERVAL '60000000 microseconds', \"timestamp\", TIMESTAMPTZ '2026-07-30 00:00:00.000000+00')"),
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
            .statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("SELECT MAX(\"timestamp\")"), "{sql}");
        assert!(sql.contains("/ 60000000) AS INTEGER)"), "{sql}");
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
        // Both records carry the connection they came from, while alerts and logs are
        // raised by a component rather than parsed from one.
        let connection = pairs(&[("connection", "serial")]);
        assert!(RecordFilter::parse(RecordTable::Messages, &connection).is_ok());
        assert!(RecordFilter::parse(RecordTable::Particles, &connection).is_ok());
        assert!(RecordFilter::parse(RecordTable::Alerts, &connection).is_err());

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
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("\"level\" = 'info'"), "{sql}");

        let several = RecordFilter::parse(
            RecordTable::Logs,
            &pairs(&[("level", "info"), ("level", "error")]),
        )
        .unwrap();
        let sql = several
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("GLOB '@deck.*'"), "{sql}");

        let filter = RecordFilter::parse(
            RecordTable::Messages,
            &pairs(&[("address", "@a"), ("address", "@b:descendants")]),
        )
        .unwrap();
        let sql = filter
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("\"type\" GLOB '*temp_high*'"), "{sql}");
        assert!(sql.contains("\"type\" GLOB 'd[[]o]or*'"), "{sql}");

        let sql = filter
            .statement(SqlDialect::Postgres, None)
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
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("instr(\"data\", x'6162') > 0"), "{sql}");
        assert!(sql.contains("substr(\"data\", 1, 1) = x'78'"), "{sql}");
        assert!(sql.contains("substr(\"data\", -2) = x'797A'"), "{sql}");

        let sql = filter
            .statement(SqlDialect::Postgres, None)
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
            .statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("\"data\" IN (x'6162', x'6364')"), "{sql}");
    }

    #[test]
    fn empty_patterns_match_like_the_python_layer() {
        // All-empty text patterns collapse to a bare true.
        let all_empty =
            RecordFilter::parse(RecordTable::Logs, &pairs(&[("contains", "")])).unwrap();
        let sql = all_empty
            .statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(sql.contains("WHERE TRUE"), "{sql}");

        // A mixed set keeps the empty pattern as a wildcard-only match.
        let mixed = RecordFilter::parse(
            RecordTable::Logs,
            &pairs(&[("contains", ""), ("contains", "x")]),
        )
        .unwrap();
        let sql = mixed
            .statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::Postgres, None)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(sql.contains("ORDER BY \"data\" DESC"), "{sql}");
    }

    #[test]
    fn bounded_counts_page_before_counting() {
        let filter =
            RecordFilter::parse(RecordTable::Particles, &pairs(&[("limit", "5")])).unwrap();
        let sql = filter
            .count_statement(SqlDialect::SqliteText, None)
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
            .statement(SqlDialect::Postgres, None)
            .to_string(sea_query::PostgresQueryBuilder);
        assert!(sql.contains("ORDER BY \"id\" ASC"), "{sql}");

        let by_content =
            RecordFilter::parse(RecordTable::Logs, &pairs(&[("order", "content:desc")])).unwrap();
        let sql = by_content
            .statement(SqlDialect::Postgres, None)
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
            .statement(SqlDialect::SqliteText, None)
            .to_string(SqliteQueryBuilder);
        assert!(
            sql.contains(
                "CAST(strftime('%H', \"timestamp\") AS INTEGER) >= 9 AND \
                 CAST(strftime('%H', \"timestamp\") AS INTEGER) < 17"
            ),
            "{sql}"
        );

        let sql = filter
            .statement(SqlDialect::Postgres, None)
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
            .statement(SqlDialect::SqliteText, None)
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
