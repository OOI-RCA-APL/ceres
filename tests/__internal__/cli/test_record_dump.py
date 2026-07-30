"""The CLI's native record dump.

A plain JSON select over a record table renders its whole output in one native pass,
so the dump must match what materializing every entity and serializing it through
Pydantic would have produced, line for line.
"""

import json
from typing import TYPE_CHECKING

from ceres import Engine
from ceres.__internal__.cli.shared import create_entity_select_command, dump_records_natively
from ceres.address import Address
from ceres.alert import Alert
from ceres.config import Config
from ceres.data import to_json, validate
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message, MessageDirection
from ceres.particle import Particle
from ceres.user import User

if TYPE_CHECKING:
    from pathlib import Path


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


async def test_the_native_dump_matches_the_materializing_path(tmp_path: Path) -> None:
    """The dump serializes each record exactly as the Python path would, one per line."""
    engine = await _build_engine_on_disk(tmp_path)
    await _write_records(engine)

    try:
        for Record in (Message, Particle, Alert, LogEntry):
            query = engine.__manager__(Record).where()
            dumped = await dump_records_natively(engine.database, Record, query)
            assert dumped is not None, f"expected a native dump for {Record.__name__}"
            assert dumped.endswith("\n")

            expected = [json.loads(to_json(entity)) for entity in await query]
            assert expected, f"expected a written {Record.__name__}"
            assert [json.loads(line) for line in dumped.splitlines()] == expected
    finally:
        await engine.database.dispose()


async def test_non_record_entities_decline_the_native_dump(tmp_path: Path) -> None:
    """Only the record tables dump natively, other entities keep the materializing path."""
    engine = await _build_engine_on_disk(tmp_path)

    try:
        query = engine.users.where()
        assert await dump_records_natively(engine.database, User, query) is None
    finally:
        await engine.database.dispose()


async def test_in_memory_databases_decline_the_native_dump() -> None:
    """A database with no native fetcher declines, leaving the materializing path."""
    from ceres.config import SQLiteDatabaseConfig
    from ceres.database import Database

    database = Database(SQLiteDatabaseConfig.in_memory())
    query = database.messages.where()
    assert await dump_records_natively(database, Message, query) is None


async def test_output_files_carry_complete_rows(tmp_path: Path) -> None:
    """`--output` files hold every field of every record, flushed by the time the
    command finishes.

    Records keep their values in native storage rather than instance attributes, so
    row extraction must read the model's fields, and the file the command opens must
    close with it or its tail never reaches disk.
    """
    engine = await _build_engine_on_disk(tmp_path)
    await _write_records(engine)
    Command = create_entity_select_command(Message)

    try:
        query = engine.__manager__(Message).where()
        expected = [json.loads(to_json(entity)) for entity in await query]
        assert expected

        csv_path = tmp_path / "messages.csv"
        command = Command(output=csv_path)
        await command.put(engine.__manager__(Message).where().select())
        lines = csv_path.read_text().splitlines()
        assert lines[0] == "id,address,timestamp,connection,direction,data"
        assert len(lines) == len(expected) + 1
        assert "@sensor.temp" in lines[1]
        assert "serial" in lines[1]

        json_path = tmp_path / "messages.json"
        command = Command(output=json_path)
        await command.put(engine.__manager__(Message).where().select())
        dumped = [json.loads(line) for line in json_path.read_text().splitlines()]
        assert dumped == expected
    finally:
        await engine.database.dispose()


def test_plain_json_output_gates_on_fields_format_and_color() -> None:
    """The native path only applies to a plain JSON dump, uncolored and unprojected."""
    Command = create_entity_select_command(Message)

    assert Command().plain_json_output() in (True, False)
    assert Command(color=False).plain_json_output() is True
    assert Command(color=True).plain_json_output() is False
    assert Command(color=False, field="id").plain_json_output() is False
    assert Command(color=False, fields=["id"]).plain_json_output() is False
    from ceres.__internal__.cli.shared import CLIDataFormat

    assert Command(color=False, data_format=CLIDataFormat.CSV).plain_json_output() is False
