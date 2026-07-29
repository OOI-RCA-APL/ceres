import json

from ceres_core import RecordBatch

from ceres import Engine
from ceres.address import Address
from ceres.alert import Alert
from ceres.config import Config
from ceres.data import to_json, validate
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message, MessageDirection
from ceres.particle import Particle


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
