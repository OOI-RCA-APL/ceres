import json
from typing import TYPE_CHECKING

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
