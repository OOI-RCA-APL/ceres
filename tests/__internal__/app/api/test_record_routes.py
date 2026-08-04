import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from ceres import Engine
from ceres.__internal__.core import NativeFilter, RecordBatch, RecordTable
from ceres.address import Address
from ceres.alert import Alert
from ceres.config import Config, SQLiteDatabaseConfig
from ceres.data import construct, to_json, validate
from ceres.database import Database

if TYPE_CHECKING:
    from pathlib import Path
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message, MessageDirection
from ceres.particle import Particle, ParticleData

RECORD_TABLES = {
    Message: RecordTable.MESSAGES,
    Particle: RecordTable.PARTICLES,
    Alert: RecordTable.ALERTS,
    LogEntry: RecordTable.LOGS,
}


async def _build_engine() -> Engine:
    engine = Engine()
    await engine.database.migrate()
    await engine.load(validate(Config, {"components": []}), checks=())
    return engine


async def _build_engine_on_disk(tmp_path: Path) -> Engine:
    """Build an engine on a file-backed database, which the native fetcher can join."""
    engine = Engine()
    await engine.load(
        validate(
            Config,
            {
                "components": [],
                "database": {"type": "sqlite", "path": str(tmp_path / "records.sqlite")},
            },
        ),
        checks=(),
    )
    await engine.database.migrate()
    return engine


async def _write_records(engine: Engine) -> None:
    address = Address("@sensor.temp")
    await engine.database.messages.create(
        Message.Create(
            address=address,
            connection="serial",
            direction=MessageDirection.RECEIVE,
            data=b"\x01\x02ABC\xff",
        )
    )
    await engine.database.particles.create(
        Particle.Create(address=address, type="sample", data={"a": 1, "b": [1.5, 2.5]})
    )
    await engine.database.alerts.create(
        Alert.Create(address=address, level=Level.WARNING, type="overheat", data={"t": 99})
    )
    await engine.database.logs.create(
        LogEntry.Create(address=address, level=Level.INFO, content="hello")
    )


async def test_native_record_batches_serialize_identically_to_the_python_path() -> None:
    """The native listing path must produce byte-equivalent JSON to Pydantic's.

    The record GET routes serialize query rows through `RecordBatch` without building
    Python entity objects, so the wire format of both paths has to stay interchangeable.
    """
    engine = await _build_engine()
    await _write_records(engine)

    for Record in (Message, Particle, Alert, LogEntry):
        query = engine.__manager__(Record).where()
        entities = await query
        assert entities, f"expected a written {Record.__name__}"
        expected = [json.loads(to_json(entity)) for entity in entities]

        batch = RecordBatch.parse(RECORD_TABLES[Record], await query.mappings())
        native = json.loads(batch.to_json())

        assert native == expected
        assert len(native) == len(entities)


async def test_live_records_serialize_natively_like_pydantic() -> None:
    """The stream path serializes entity objects natively with identical wire output."""
    engine = await _build_engine()
    await _write_records(engine)

    for Record in (Message, Particle, Alert, LogEntry):
        for entity in await engine.__manager__(Record).where():
            native = RecordBatch.record_to_json(RECORD_TABLES[Record], entity)
            assert json.loads(native) == json.loads(to_json(entity))

    particle = Particle(address=Address("@sensor.temp"), type="sample", data={"a": 1}, span=(3, 17))
    native = json.loads(RecordBatch.record_to_json(RecordTable.PARTICLES, particle))
    assert native["span"] == [3, 17]
    assert native == json.loads(to_json(particle))


async def test_typed_payloads_refuse_native_serialization() -> None:
    """A typed payload's Pydantic serialization can differ, so the native path rejects it.

    Validated construction coerces mapping payloads into plain dictionaries, so a typed
    payload on a base particle only arises through unvalidated construction, the same way
    the live parsing paths build records.
    """

    class TypedData(ParticleData):
        a: int

    particle = construct(
        Particle, address=Address("@sensor.temp"), type="sample", data=TypedData(a=1)
    )
    with pytest.raises(ValueError):
        RecordBatch.record_to_json(RecordTable.PARTICLES, particle)


async def test_native_fetches_serialize_identically_to_the_python_path(
    tmp_path: Path,
) -> None:
    """The fully-native fetch path must match Pydantic's serialization byte for byte.

    A file-backed database is required, the native fetcher cannot join a private in-memory
    database and reports itself unavailable there.
    """
    engine = await _build_engine_on_disk(tmp_path)
    await _write_records(engine)

    fetcher = engine.database._record_fetcher()
    assert fetcher is not None

    dialect = engine.database.type.value
    for Record in (Message, Particle, Alert, LogEntry):
        entities = await engine.__manager__(Record).where()
        assert entities, f"expected a written {Record.__name__}"
        expected = [json.loads(to_json(entity)) for entity in entities]

        sql, parameters = NativeFilter.from_pairs(Record.__entity_naming__.table, []).compiled(
            dialect
        )
        batch = await fetcher.fetch_sql(RECORD_TABLES[Record], sql, parameters)
        assert json.loads(batch.to_json()) == expected

    sql, parameters = NativeFilter.from_pairs(
        Particle.__entity_naming__.table, [("limit", "1")]
    ).compiled(dialect)
    limited = await fetcher.fetch_sql(RecordTable.PARTICLES, sql, parameters)
    assert len(json.loads(limited.to_json())) == 1


async def test_compiled_queries_fetch_natively_for_any_filter(tmp_path: Path) -> None:
    """The native path executes the query layer's own compiled SQL, so filters need no port.

    The filters here cover the awkward constructs on purpose, address selectors, relative
    time ranges, boolean combinators, level matching, and subsampling with its CTE.
    """
    engine = await _build_engine_on_disk(tmp_path)
    await _write_records(engine)
    await engine.database.particles.create(
        Particle.Create(address=Address("@other.unit"), type="status", data={"ok": True})
    )

    fetcher = engine.database._record_fetcher()
    assert fetcher is not None

    async def check(query: Any) -> None:
        entities = await query
        expected = [json.loads(to_json(entity)) for entity in entities]
        sql, parameters = await query.compiled()
        batch = await fetcher.fetch_sql(RecordTable.PARTICLES, sql, parameters)
        assert json.loads(batch.to_json()) == expected

    particles = engine.database.particles
    await check(particles.where(address="@sensor.temp:all"))
    await check(particles.where(type="sample"))
    await check(particles.where(type="nothing-matches"))
    await check(
        particles.where(after=datetime(2000, 1, 1, tzinfo=UTC), timespan=timedelta(days=36500))
    )
    await check(particles.where(max_age=timedelta(days=1), order="timestamp:desc", limit=1))
    await check(
        particles.where(validate(Particle.Filter, {"or": [{"type": "sample"}, {"type": "status"}]}))
    )

    # Subsampling exercises the CTE and the `floor` math function the bundled SQLite
    # compiles in specifically for it.
    await check(
        particles.where(
            after=datetime(2000, 1, 1, tzinfo=UTC),
            before=datetime(2100, 1, 1, tzinfo=UTC),
            subsample=4,
        )
    )

    alerts = engine.database.alerts
    entities = await alerts.where(level=Level.WARNING)
    sql, parameters = await alerts.where(level=Level.WARNING).compiled()
    batch = await fetcher.fetch_sql(RecordTable.ALERTS, sql, parameters)
    assert json.loads(batch.to_json()) == [json.loads(to_json(entity)) for entity in entities]


async def test_a_temporary_database_still_reports_a_native_fetcher() -> None:
    """A path nobody configured is still a path, so the native fetcher can join it."""
    database = Database(SQLiteDatabaseConfig())
    try:
        assert database._record_fetcher() is not None
    finally:
        await database.dispose()


async def test_native_writes_read_back_identically(tmp_path: Path) -> None:
    """Records written natively must read back exactly like query layer writes.

    The same flush then rewrites a record under its ID, proving the upsert updates rather
    than duplicates.
    """
    from ceres.__internal__.database.writer import Writer

    engine = await _build_engine_on_disk(tmp_path)
    db = engine.database
    writer = Writer(lambda: db)

    address = Address("@sensor.temp")
    records = [
        Message(address=address, direction=MessageDirection.RECEIVE, data=b"\x00A\xff"),
        Particle(address=address, type="sample", data={"a": 1, "b": [1.5]}),
        Alert(address=address, level=Level.ERROR, type="overheat", data={"t": 99}),
        LogEntry(address=address, level=Level.INFO, content="hello"),
    ]
    assert await writer._write_natively(db, records)

    for record, manager in zip(
        records, (db.messages, db.particles, db.alerts, db.logs), strict=True
    ):
        stored = await manager.where()
        assert [json.loads(to_json(entity)) for entity in stored] == [json.loads(to_json(record))]

    rewritten = LogEntry(
        id=records[3].id,
        address=address,
        timestamp=records[3].timestamp,
        level=Level.WARNING,
        content="revised",
    )
    assert await writer._write_natively(db, [rewritten])
    stored = await db.logs.where()
    assert len(stored) == 1
    assert stored[0].content == "revised"
    assert stored[0].level == Level.WARNING


async def test_unsupported_flushes_decline_the_native_writer(tmp_path: Path) -> None:
    """A typed payload sends the whole flush down the query layer."""
    from ceres.__internal__.database.writer import Writer

    engine = await _build_engine_on_disk(tmp_path)
    db = engine.database
    writer = Writer(lambda: db)

    class TypedData(ParticleData):
        a: int

    typed = construct(Particle, address=Address("@sensor.temp"), type="sample", data=TypedData(a=1))
    assert not await writer._write_natively(db, [typed])


@pytest.mark.databases("postgres")
async def test_native_fetches_match_on_postgres(database: str) -> None:
    """The native Postgres pool must see the same rows the query layer does.

    The test harness isolates tests in per-test schemas through `search_path`, so this
    also proves connection server settings reach the native pool.
    """
    db = Database()
    await db.migrate()

    address = Address("@sensor.temp")
    await db.messages.create(
        Message.Create(address=address, direction=MessageDirection.SEND, data=b"A\xffB")
    )
    await db.particles.create(Particle.Create(address=address, type="sample", data={"a": 1}))

    fetcher = db._record_fetcher()
    assert fetcher is not None

    for manager, table in (
        (db.messages, RecordTable.MESSAGES),
        (db.particles, RecordTable.PARTICLES),
    ):
        query = manager.where()
        expected = [json.loads(to_json(entity)) for entity in await query]
        assert expected

        sql, parameters = await query.compiled()
        batch = await fetcher.fetch_sql(table, sql, parameters)
        assert json.loads(batch.to_json()) == expected

    # A filtered query binds parameters the Postgres driver takes natively.
    query = db.particles.where(type="sample", max_age=timedelta(days=1))
    expected = [json.loads(to_json(entity)) for entity in await query]
    sql, parameters = await query.compiled()
    batch = await fetcher.fetch_sql(RecordTable.PARTICLES, sql, parameters)
    assert json.loads(batch.to_json()) == expected

    # Native writes land through the same pool rules, JSON payload column included.
    writer = db._record_writer()
    assert writer is not None
    written = Particle(address=address, type="native", data={"x": [1, 2]})
    await writer.write([(RecordTable.PARTICLES, [written])])
    stored = await db.particles.where(type="native")
    assert [json.loads(to_json(entity)) for entity in stored] == [json.loads(to_json(written))]


@pytest.mark.databases("turso")
async def test_turso_databases_serve_the_native_paths(database: str) -> None:
    """Turso reads and writes through the same engine everything else does.

    Turso coordinates the engines sharing a file through in-process state and an fcntl
    lock, and fcntl locks never conflict within one process, so two copies of the engine
    here would overwrite each other's WAL frames. There is one copy now, which is what
    makes this safe rather than the paths having become safe on their own.
    """
    db = Database()
    try:
        assert db._record_fetcher() is not None
        assert db._record_writer() is not None
        assert db._store() is not None
    finally:
        await db.dispose()


async def test_typed_particle_queries_keep_the_materializing_path() -> None:
    """A particle query carrying a class transform reports one, so routes fall back."""
    engine = await _build_engine()
    await _write_records(engine)

    plain = engine.__manager__(Particle).where()
    assert plain._get_transform() is None

    typed = engine.database.particles.where(
        validate(Particle.Filter, {"class": "ceres.particle.Particle"})
    )
    assert typed._get_transform() is not None
