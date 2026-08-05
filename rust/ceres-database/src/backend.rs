//! One trait every database backend implements, and the three that do.
//!
//! Everything above this file works in sea-query statements and compiled SQL, and knows
//! a backend only by what it can be asked to do. The differences that remain, which
//! query builder renders a statement, how a parameter binds, how a row decodes, and how
//! a transaction opens, live behind [`DatabaseBackend`] rather than in a match arm at
//! every call site.
//!
//! Adding a backend means writing one impl. Adding an operation means adding one method
//! and implementing it three times, which is the trade this shape makes deliberately: a
//! new operation costs more than it did, a new backend costs far less, and no caller can
//! forget a backend because the compiler will not let it.

use async_trait::async_trait;
use ceres_entities::{Entities, Records};
use sea_query::{
    DeleteStatement, InsertStatement, PostgresQueryBuilder, SelectStatement, SqliteQueryBuilder,
    UpdateStatement,
};
use sea_query_binder::SqlxBinder;
use sqlx::Row as _;

use crate::dynamic::{Row, Table};
use crate::entities::{DecodeEntities, EntityTable};
use crate::filter::SqlDialect;
use crate::records::{DecodeRecords, RecordTable};
use crate::store::{Error, GateUser, Parameter};
use crate::turso::{parameter_value, sea_value};

/// How a transaction means to sit beside other writers.
///
/// This is the caller's intent rather than a promise about the backend. One that cannot
/// overlap writers runs a [`Writing::Concurrent`] transaction the only way it can, so ask
/// [`DatabaseBackend::overlaps_writers`] when the answer changes what a caller does.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum Writing {
    /// However the backend opens a transaction by default.
    ///
    /// Anything holding a lock, changing the schema, or needing to see a consistent
    /// database for its whole duration belongs here.
    #[default]
    Default,

    /// Overlap other writers wherever the backend can.
    ///
    /// The transactions are optimistic, so two that touch the same rows both proceed and
    /// the second fails when it commits. A caller asking for this is saying its writes
    /// are frequent, independent, and safe to retry.
    Concurrent,
}

/// A built statement that changes the rows a filter matched.
///
/// The two shapes are kept apart rather than rendered to text early, because each backend
/// renders with its own query builder and a `RETURNING` clause is added before that
/// happens. An insert is not here, [`DatabaseBackend::insert_all`] taking its statements
/// directly because it writes several in one transaction rather than one in its own.
pub(crate) enum Write {
    Update(UpdateStatement),
    Delete(DeleteStatement),
}

/// Where a streamed operation hands each chunk as it decodes.
pub(crate) type Sink<'a, T> = &'a mut (dyn FnMut(T) -> Result<(), Error> + Send);

/// A load's batches, pulled one at a time so the reader behind them walks as it writes.
///
/// A batch of `Err` is a row the reader refused, which rolls the transaction back. The
/// count rides along because a batch of records knows how many rows it carries and the
/// statement it renders to does not.
pub(crate) type Batches<'a> =
    &'a mut (dyn Iterator<Item = Result<(InsertStatement, usize), String>> + Send);

/// One database backend, as the store and the writer need it.
///
/// Every method takes a built statement or compiled SQL and answers in this crate's own
/// types, so nothing above here handles a driver's rows, arguments, or pool.
#[async_trait]
pub(crate) trait DatabaseBackend: Send + Sync {
    /// The value forms this backend binds, which is what a filter renders against.
    fn dialect(&self) -> SqlDialect;

    /// Whether two write transactions on this database can overlap.
    ///
    /// `false` means a [`Writing::Concurrent`] transaction ran serialized, because the
    /// backend has one writer or was not configured for more. Callers that would retry a
    /// commit conflict use this to say whether one is possible at all.
    fn overlaps_writers(&self) -> bool;

    /// Run a select, decoding its rows as records of `table`.
    async fn select_records(
        &self,
        table: RecordTable,
        statement: SelectStatement,
    ) -> Result<Records, Error>;

    /// Run a select, handing decoded records over a chunk at a time.
    async fn stream_records(
        &self,
        table: RecordTable,
        statement: SelectStatement,
        sink: Sink<'_, Records>,
    ) -> Result<(), Error>;

    /// The entity form of [`Self::stream_records`].
    async fn stream_entities(
        &self,
        table: EntityTable,
        statement: SelectStatement,
        sink: Sink<'_, Entities>,
    ) -> Result<(), Error>;

    /// Run a select whose first column is a count.
    async fn count(&self, statement: SelectStatement) -> Result<u64, Error>;

    /// Run a select whose first column says whether any row matched.
    ///
    /// Separate from [`Self::count`] because the backends disagree on what an `EXISTS`
    /// column decodes as, and because a caller asking this can stop at the first row.
    async fn exists(&self, statement: SelectStatement) -> Result<bool, Error>;

    /// Run one write in a transaction of its own, answering how many rows changed.
    async fn write(&self, statement: Write) -> Result<u64, Error>;

    /// Run one write that hands its rows back, in a transaction of its own.
    async fn write_records(&self, table: RecordTable, statement: Write) -> Result<Records, Error>;

    /// The entity form of [`Self::write_records`].
    async fn write_entities(&self, table: EntityTable, statement: Write)
    -> Result<Entities, Error>;

    /// Insert every batch in one transaction, answering how many rows landed.
    ///
    /// Nothing lands unless all of them do, so a refused batch or a failing statement
    /// leaves the tables exactly as they were.
    async fn insert_all(&self, writing: Writing, batches: Batches<'_>) -> Result<usize, Error>;

    /// Run compiled SQL, decoding its rows as records of `table`.
    async fn query_records(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Parameter>,
    ) -> Result<Records, Error>;

    /// The chunked form of [`Self::query_records`].
    async fn stream_query_records(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Parameter>,
        sink: Sink<'_, Records>,
    ) -> Result<(), Error>;

    /// Run compiled SQL, decoding its rows by column rather than into a table's struct.
    ///
    /// `table` says which of the columns hold UUIDs and timestamps where the storage
    /// class alone cannot, which is every text-storing backend. `None` reads values as
    /// stored, which is what a migration or a catalog query wants.
    async fn query_rows(
        &self,
        table: Option<Table>,
        sql: &str,
        parameters: Vec<Parameter>,
    ) -> Result<Vec<Row>, Error>;

    /// The chunked form of [`Self::query_rows`].
    async fn stream_rows(
        &self,
        table: Option<Table>,
        sql: &str,
        parameters: Vec<Parameter>,
        sink: Sink<'_, Vec<Row>>,
    ) -> Result<(), Error>;

    /// Run compiled SQL that returns no rows, answering how many it touched.
    async fn execute(&self, sql: &str, parameters: Vec<Parameter>) -> Result<u64, Error>;

    /// Run a script of `;`-separated statements.
    ///
    /// The driver separates them rather than this guessing where one ends. A migration
    /// relies on that, since a `PRAGMA` the SQLite family needs before rebuilding a table
    /// does nothing inside a transaction someone else opened.
    async fn execute_script(&self, sql: &str) -> Result<(), Error>;

    /// Read the standing an authentication gate needs for one user.
    async fn gate_user(&self, id: uuid::Uuid) -> Result<Option<GateUser>, Error>;
}

impl From<UpdateStatement> for Write {
    fn from(statement: UpdateStatement) -> Self {
        Write::Update(statement)
    }
}

impl From<DeleteStatement> for Write {
    fn from(statement: DeleteStatement) -> Self {
        Write::Delete(statement)
    }
}

impl Write {
    /// Render this statement with `builder`, as SQL text and bound values.
    fn build_sqlx<B: sea_query::QueryBuilder>(
        self,
        builder: B,
    ) -> (String, sea_query_binder::SqlxValues) {
        match self {
            Write::Update(statement) => statement.build_sqlx(builder),
            Write::Delete(statement) => statement.build_sqlx(builder),
        }
    }

    /// Render this statement with `builder`, as SQL text and sea-query values.
    fn build<B: sea_query::QueryBuilder>(self, builder: B) -> (String, sea_query::Values) {
        match self {
            Write::Update(statement) => statement.build(builder),
            Write::Delete(statement) => statement.build(builder),
        }
    }
}

/// How many rows one streamed chunk carries.
///
/// A dump decodes, renders, and writes per chunk rather than whole, so memory stays flat
/// over a table of any size. The size also decides how much of a result a caller can
/// hold back before writing, which is what keeps a late refusal able to delegate.
pub const CHUNK: usize = 1000;

/// Walk a row cursor, decoding and handing over one chunk at a time.
///
/// A chunk decodes only once it is full, so a decode failure surfaces having produced no
/// partial batch, and the trailing rows go over even when they do not fill one.
pub(crate) async fn drain<R, Batch, Cursor>(
    cursor: &mut Cursor,
    decode: impl Fn(Vec<R>) -> Result<Batch, Error>,
    sink: &mut (impl FnMut(Batch) -> Result<(), Error> + ?Sized),
) -> Result<(), Error>
where
    Cursor: futures_util::Stream<Item = Result<R, sqlx::Error>> + Unpin,
{
    use futures_util::StreamExt;

    let mut buffer = Vec::with_capacity(CHUNK);
    let mut sent = false;
    while let Some(row) = cursor.next().await {
        buffer.push(row?);
        if buffer.len() == CHUNK {
            sink(decode(std::mem::take(&mut buffer))?)?;
            sent = true;
            buffer.reserve(CHUNK);
        }
    }

    // An empty result still reaches the sink once, because a CSV dump writes its header
    // row whether or not any record follows it.
    if !buffer.is_empty() || !sent {
        sink(decode(buffer)?)?;
    }

    Ok(())
}

/// Declare a `DatabaseBackend` over one of sqlx's pools.
///
/// SQLite and PostgreSQL differ only in which query builder renders a statement, how a
/// compiled parameter binds, and how a row decodes into this crate's types. Each of those
/// is a type or a function name, so the bodies are the same text twice and this writes
/// them rather than a reader checking that two hand-written copies still agree.
///
/// Neither honors [`Writing::Concurrent`] specially. PostgreSQL already overlaps writers,
/// its transactions being optimistic by nature, and SQLite admits one writer at a time
/// whatever a transaction asks for. `overlaps_writers` is what tells them apart.
macro_rules! sqlx_backend {
    (
        $name:ident,
        pool = $pool:ty,
        builder = $builder:expr,
        dialect = $dialect:expr,
        bind = $bind:path,
        overlaps = $overlaps:expr,
        row = |$row:ident, $table:ident| $decode_row:expr,
        gate = |$id:ident| ($gate_sql:expr, $gate_bind:expr),
    ) => {
        /// A pool of connections to one database, serving every operation the store runs.
        pub(crate) struct $name(pub(crate) $pool);

        #[async_trait]
        impl DatabaseBackend for $name {
            fn dialect(&self) -> SqlDialect {
                $dialect
            }

            fn overlaps_writers(&self) -> bool {
                $overlaps
            }

            async fn select_records(
                &self,
                table: RecordTable,
                statement: SelectStatement,
            ) -> Result<Records, Error> {
                let (sql, values) = statement.build_sqlx($builder);
                let rows = sqlx::query_with(&sql, values).fetch_all(&self.0).await?;
                DecodeRecords::decode(table, rows)
            }

            async fn stream_records(
                &self,
                table: RecordTable,
                statement: SelectStatement,
                sink: Sink<'_, Records>,
            ) -> Result<(), Error> {
                let (sql, values) = statement.build_sqlx($builder);
                let mut cursor = sqlx::query_with(&sql, values).fetch(&self.0);
                drain(&mut cursor, |rows| DecodeRecords::decode(table, rows), sink).await
            }

            async fn stream_entities(
                &self,
                table: EntityTable,
                statement: SelectStatement,
                sink: Sink<'_, Entities>,
            ) -> Result<(), Error> {
                let (sql, values) = statement.build_sqlx($builder);
                let mut cursor = sqlx::query_with(&sql, values).fetch(&self.0);
                drain(
                    &mut cursor,
                    |rows| DecodeEntities::decode(table, rows),
                    sink,
                )
                .await
            }

            async fn count(&self, statement: SelectStatement) -> Result<u64, Error> {
                let (sql, values) = statement.build_sqlx($builder);
                let row = sqlx::query_with(&sql, values).fetch_one(&self.0).await?;
                let count: i64 = row.try_get(0)?;
                Ok(count.max(0) as u64)
            }

            async fn exists(&self, statement: SelectStatement) -> Result<bool, Error> {
                let (sql, values) = statement.build_sqlx($builder);
                let row = sqlx::query_with(&sql, values).fetch_one(&self.0).await?;
                Ok(row.try_get(0)?)
            }

            async fn write(&self, statement: Write) -> Result<u64, Error> {
                let (sql, values) = statement.build_sqlx($builder);
                let mut transaction = self.0.begin().await?;
                let affected = sqlx::query_with(&sql, values)
                    .execute(&mut *transaction)
                    .await?
                    .rows_affected();
                transaction.commit().await?;
                Ok(affected)
            }

            async fn write_records(
                &self,
                table: RecordTable,
                statement: Write,
            ) -> Result<Records, Error> {
                let (sql, values) = statement.build_sqlx($builder);
                let mut transaction = self.0.begin().await?;
                let rows = sqlx::query_with(&sql, values)
                    .fetch_all(&mut *transaction)
                    .await?;
                transaction.commit().await?;
                DecodeRecords::decode(table, rows)
            }

            async fn write_entities(
                &self,
                table: EntityTable,
                statement: Write,
            ) -> Result<Entities, Error> {
                let (sql, values) = statement.build_sqlx($builder);
                let mut transaction = self.0.begin().await?;
                let rows = sqlx::query_with(&sql, values)
                    .fetch_all(&mut *transaction)
                    .await?;
                transaction.commit().await?;
                DecodeEntities::decode(table, rows)
            }

            async fn insert_all(
                &self,
                _writing: Writing,
                batches: Batches<'_>,
            ) -> Result<usize, Error> {
                let mut transaction = self.0.begin().await?;
                let mut written = 0;
                for batch in batches {
                    // Dropping the transaction rolls it back, so the tables are exactly
                    // as they were and the refusal is the caller's own to report.
                    let (statement, rows) = batch.map_err(Error::Refused)?;
                    let (sql, values) = statement.build_sqlx($builder);
                    sqlx::query_with(&sql, values)
                        .execute(&mut *transaction)
                        .await?;
                    written += rows;
                }

                transaction.commit().await?;
                Ok(written)
            }

            async fn query_records(
                &self,
                table: RecordTable,
                sql: &str,
                parameters: Vec<Parameter>,
            ) -> Result<Records, Error> {
                let rows = $bind(sqlx::query(sql), parameters)
                    .fetch_all(&self.0)
                    .await?;
                DecodeRecords::decode(table, rows)
            }

            async fn stream_query_records(
                &self,
                table: RecordTable,
                sql: &str,
                parameters: Vec<Parameter>,
                sink: Sink<'_, Records>,
            ) -> Result<(), Error> {
                let mut cursor = $bind(sqlx::query(sql), parameters).fetch(&self.0);
                drain(&mut cursor, |rows| DecodeRecords::decode(table, rows), sink).await
            }

            async fn query_rows(
                &self,
                table: Option<Table>,
                sql: &str,
                parameters: Vec<Parameter>,
            ) -> Result<Vec<Row>, Error> {
                $bind(sqlx::query(sql), parameters)
                    .fetch_all(&self.0)
                    .await?
                    .iter()
                    .map(|$row| {
                        let $table = table;
                        $decode_row
                    })
                    .collect()
            }

            async fn stream_rows(
                &self,
                table: Option<Table>,
                sql: &str,
                parameters: Vec<Parameter>,
                sink: Sink<'_, Vec<Row>>,
            ) -> Result<(), Error> {
                let mut cursor = $bind(sqlx::query(sql), parameters).fetch(&self.0);
                drain(
                    &mut cursor,
                    |rows| {
                        rows.iter()
                            .map(|$row| {
                                let $table = table;
                                $decode_row
                            })
                            .collect()
                    },
                    sink,
                )
                .await
            }

            async fn execute(&self, sql: &str, parameters: Vec<Parameter>) -> Result<u64, Error> {
                Ok($bind(sqlx::query(sql), parameters)
                    .execute(&self.0)
                    .await?
                    .rows_affected())
            }

            async fn execute_script(&self, sql: &str) -> Result<(), Error> {
                sqlx::raw_sql(sql).execute(&self.0).await?;
                Ok(())
            }

            async fn gate_user(&self, id: uuid::Uuid) -> Result<Option<GateUser>, Error> {
                let $id = id;
                let (sql, bound) = ($gate_sql, $gate_bind);
                let row = sqlx::query(&sql)
                    .bind(bound)
                    .fetch_optional(&self.0)
                    .await?;
                row.map(|row| {
                    Ok(GateUser {
                        id,
                        admin: row.try_get("admin")?,
                        disabled: row.try_get("disabled")?,
                    })
                })
                .transpose()
            }
        }
    };
}

/// The columns an authentication gate reads, without the placeholder each backend spells
/// its own way.
const GATE_SQL: &str = "SELECT \"admin\", \"disabled\" FROM \"users\" WHERE \"id\" = ";

sqlx_backend!(
    SqliteBackend,
    pool = sqlx::SqlitePool,
    builder = SqliteQueryBuilder,
    dialect = SqlDialect::SqliteText,
    bind = bind_sqlite,
    // One writer at a time, whatever a transaction asks for.
    overlaps = false,
    row = |row, table| crate::dynamic::sqlite_row(row, table),
    gate = |id| (format!("{GATE_SQL}?"), id.to_string()),
);

sqlx_backend!(
    PostgresBackend,
    pool = sqlx::PgPool,
    builder = PostgresQueryBuilder,
    dialect = SqlDialect::Postgres,
    bind = bind_postgres,
    // MVCC is how this backend works, so writers already overlap and a concurrent
    // transaction is what it opens anyway.
    overlaps = true,
    row = |row, table| {
        let _ = table;
        crate::dynamic::postgres_row(row)
    },
    gate = |id| (format!("{GATE_SQL}$1"), id),
);

/// Bind compiled parameters onto a SQLite statement.
///
/// SQLite stores timestamps and UUIDs as text, so those bind in the stored form rather
/// than as their own types, or equality against a stored row misses.
fn bind_sqlite<'q>(
    mut query: sqlx::query::Query<'q, sqlx::Sqlite, sqlx::sqlite::SqliteArguments<'q>>,
    parameters: Vec<Parameter>,
) -> sqlx::query::Query<'q, sqlx::Sqlite, sqlx::sqlite::SqliteArguments<'q>> {
    for parameter in parameters {
        query = match parameter {
            Parameter::Null => query.bind(None::<String>),
            Parameter::Bool(value) => query.bind(value),
            Parameter::Integer(value) => query.bind(value),
            Parameter::Float(value) => query.bind(value),
            Parameter::Text(value) => query.bind(value),
            Parameter::Bytes(value) => query.bind(value),
            Parameter::Timestamp(value) => query.bind(Parameter::timestamp_text(&value)),
            Parameter::Uuid(value) => query.bind(value.to_string()),
            Parameter::Json(value) => query.bind(value.to_string()),
        };
    }

    query
}

/// Bind compiled parameters onto a PostgreSQL statement, which takes timestamps and
/// UUIDs as themselves.
fn bind_postgres<'q>(
    mut query: sqlx::query::Query<'q, sqlx::Postgres, sqlx::postgres::PgArguments>,
    parameters: Vec<Parameter>,
) -> sqlx::query::Query<'q, sqlx::Postgres, sqlx::postgres::PgArguments> {
    for parameter in parameters {
        query = match parameter {
            Parameter::Null => query.bind(None::<String>),
            Parameter::Bool(value) => query.bind(value),
            Parameter::Integer(value) => query.bind(value),
            Parameter::Float(value) => query.bind(value),
            Parameter::Text(value) => query.bind(value),
            Parameter::Bytes(value) => query.bind(value),
            Parameter::Timestamp(value) => query.bind(value),
            Parameter::Uuid(value) => query.bind(value),
            Parameter::Json(value) => query.bind(value),
        };
    }

    query
}

/// Render a statement for the SQLite family and convert its values for Turso's driver.
pub(crate) fn turso_sql<S>(statement: S) -> Result<(String, Vec<turso::Value>), Error>
where
    S: sea_query::QueryStatementWriter,
{
    let (sql, values) = statement.build(SqliteQueryBuilder);
    let parameters = values
        .into_iter()
        .map(sea_value)
        .collect::<Result<Vec<_>, _>>()?;
    Ok((sql, parameters))
}

/// The [`Write`] form of [`turso_sql`], which cannot go through the same generic because
/// the statement shapes are behind an enum.
fn turso_write(statement: Write) -> Result<(String, Vec<turso::Value>), Error> {
    let (sql, values) = statement.build(SqliteQueryBuilder);
    let parameters = values
        .into_iter()
        .map(sea_value)
        .collect::<Result<Vec<_>, _>>()?;
    Ok((sql, parameters))
}

#[async_trait]
impl DatabaseBackend for crate::turso::TursoBackend {
    fn dialect(&self) -> SqlDialect {
        // Turso reads and writes SQLite's file format, so values take the same forms and
        // statements render with the same builder.
        SqlDialect::SqliteText
    }

    fn overlaps_writers(&self) -> bool {
        // Only under MVCC journaling. Without it Turso admits one writer, the same as
        // SQLite, and a concurrent transaction opens plainly.
        self.mvcc()
    }

    async fn select_records(
        &self,
        table: RecordTable,
        statement: SelectStatement,
    ) -> Result<Records, Error> {
        let (sql, parameters) = turso_sql(statement)?;
        self.query(table, &sql, parameters).await
    }

    async fn stream_records(
        &self,
        table: RecordTable,
        statement: SelectStatement,
        sink: Sink<'_, Records>,
    ) -> Result<(), Error> {
        let (sql, parameters) = turso_sql(statement)?;
        self.stream(table, &sql, parameters, sink).await
    }

    async fn stream_entities(
        &self,
        table: EntityTable,
        statement: SelectStatement,
        sink: Sink<'_, Entities>,
    ) -> Result<(), Error> {
        let (sql, parameters) = turso_sql(statement)?;
        self.stream_entities(table, &sql, parameters, sink).await
    }

    async fn count(&self, statement: SelectStatement) -> Result<u64, Error> {
        let (sql, parameters) = turso_sql(statement)?;
        self.scalar_count(&sql, parameters).await
    }

    async fn exists(&self, statement: SelectStatement) -> Result<bool, Error> {
        // An `EXISTS` column arrives as the integer the SQLite family stores a boolean
        // as, so the count reader answers it.
        let (sql, parameters) = turso_sql(statement)?;
        Ok(self.scalar_count(&sql, parameters).await? > 0)
    }

    async fn write(&self, statement: Write) -> Result<u64, Error> {
        let (sql, parameters) = turso_write(statement)?;
        self.execute_write(&sql, parameters).await
    }

    async fn write_records(&self, table: RecordTable, statement: Write) -> Result<Records, Error> {
        let (sql, parameters) = turso_write(statement)?;
        self.query_write(table, &sql, parameters).await
    }

    async fn write_entities(
        &self,
        table: EntityTable,
        statement: Write,
    ) -> Result<Entities, Error> {
        let (sql, parameters) = turso_write(statement)?;
        self.query_write_entities(table, &sql, parameters).await
    }

    async fn insert_all(&self, writing: Writing, batches: Batches<'_>) -> Result<usize, Error> {
        // Turso takes its statements together rather than one at a time, so the batches
        // render here and the transaction is opened around all of them.
        let mut statements = Vec::new();
        let mut written = 0;
        for batch in batches {
            let (statement, rows) = batch.map_err(Error::Refused)?;
            statements.push(turso_sql(statement)?);
            written += rows;
        }

        self.execute_transaction(writing, statements).await?;
        Ok(written)
    }

    async fn query_records(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Parameter>,
    ) -> Result<Records, Error> {
        self.query(table, sql, values(parameters)).await
    }

    async fn stream_query_records(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Parameter>,
        sink: Sink<'_, Records>,
    ) -> Result<(), Error> {
        self.stream(table, sql, values(parameters), sink).await
    }

    async fn query_rows(
        &self,
        table: Option<Table>,
        sql: &str,
        parameters: Vec<Parameter>,
    ) -> Result<Vec<Row>, Error> {
        self.query_dynamic(table, sql, values(parameters)).await
    }

    async fn stream_rows(
        &self,
        table: Option<Table>,
        sql: &str,
        parameters: Vec<Parameter>,
        sink: Sink<'_, Vec<Row>>,
    ) -> Result<(), Error> {
        self.stream_dynamic(table, sql, values(parameters), sink)
            .await
    }

    async fn execute(&self, sql: &str, parameters: Vec<Parameter>) -> Result<u64, Error> {
        self.execute_dynamic(sql, values(parameters)).await
    }

    async fn execute_script(&self, sql: &str) -> Result<(), Error> {
        self.execute_script(sql).await
    }

    async fn gate_user(&self, id: uuid::Uuid) -> Result<Option<GateUser>, Error> {
        self.gate_user(&format!("{GATE_SQL}?"), id).await
    }
}

/// Compiled parameters in the forms Turso's driver takes, which are SQLite's.
fn values(parameters: Vec<Parameter>) -> Vec<turso::Value> {
    parameters.into_iter().map(parameter_value).collect()
}
