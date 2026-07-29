import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from ceres_core import RecordBatch

from ceres import Engine
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

        batch = RecordBatch.parse(Record.__entity_naming__.table, await query.mappings())
        native = json.loads(batch.to_json())

        assert native == expected
        assert len(batch) == len(entities)


async def test_live_records_serialize_natively_like_pydantic() -> None:
    """The stream path serializes entity objects natively with identical wire output."""
    engine = await _build_engine()
    await _write_records(engine)

    for Record in (Message, Particle, Alert, LogEntry):
        for entity in await engine.__manager__(Record).where():
            native = RecordBatch.record_to_json(Record.__entity_naming__.table, entity)
            assert json.loads(native) == json.loads(to_json(entity))

    particle = Particle(address=Address("@sensor.temp"), type="sample", data={"a": 1}, span=(3, 17))
    native = json.loads(RecordBatch.record_to_json("particles", particle))
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
        RecordBatch.record_to_json("particles", particle)


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

    for Record in (Message, Particle, Alert, LogEntry):
        entities = await engine.__manager__(Record).where()
        assert entities, f"expected a written {Record.__name__}"
        expected = [json.loads(to_json(entity)) for entity in entities]

        batch = await fetcher.fetch(Record.__entity_naming__.table)
        assert json.loads(batch.to_json()) == expected

    limited = await fetcher.fetch("particles", 1, 0)
    assert len(limited) == 1


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
        batch = await fetcher.fetch_sql("particles", sql, parameters)
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

    # Subsampling compiles a `floor` call the native SQLite build does not ship yet, the
    # route falls back to the query layer when the native engine reports the error.
    subsampled = particles.where(
        after=datetime(2000, 1, 1, tzinfo=UTC),
        before=datetime(2100, 1, 1, tzinfo=UTC),
        subsample=4,
    )
    sql, parameters = await subsampled.compiled()
    with pytest.raises(ValueError):
        await fetcher.fetch_sql("particles", sql, parameters)

    alerts = engine.database.alerts
    entities = await alerts.where(level=Level.WARNING)
    sql, parameters = await alerts.where(level=Level.WARNING).compiled()
    batch = await fetcher.fetch_sql("alerts", sql, parameters)
    assert json.loads(batch.to_json()) == [json.loads(to_json(entity)) for entity in entities]


async def test_in_memory_databases_report_no_native_fetcher() -> None:
    database = Database(SQLiteDatabaseConfig.in_memory())
    assert database._record_fetcher() is None


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
