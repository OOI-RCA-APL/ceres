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
    # A payload full of CSV metacharacters, and no connection, exercise quoting and
    # empty cells.
    await engine.database.messages.create(
        Message.Create(
            address=address,
            direction=MessageDirection.SEND,
            data=b'a,"b"\r\nc',
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


async def test_the_native_csv_dump_matches_the_materializing_path(tmp_path: Path) -> None:
    """The native CSV render is byte-identical to extracting and writing every row in
    Python, header, quoting, and empty cells included.
    """
    from ceres.__internal__.cli.shared import CLIDataFormat, create_entity_select_command

    engine = await _build_engine_on_disk(tmp_path)
    await _write_records(engine)

    try:
        for Record in (Message, Particle, Alert, LogEntry):
            query = engine.__manager__(Record).where()
            dumped = await dump_records_natively(engine.database, Record, query, CLIDataFormat.CSV)
            assert dumped is not None, f"expected a native CSV dump for {Record.__name__}"

            expected_path = tmp_path / f"{Record.__name__}.csv"
            Command = create_entity_select_command(Record)
            command = Command(output=expected_path)
            await command.put(engine.__manager__(Record).where().select())
            # Bytes keep the file verbatim, text reads would fold a quoted CRLF.
            assert dumped == expected_path.read_bytes().decode(), Record.__name__
    finally:
        await engine.database.dispose()


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
        with csv_path.open(newline="") as file:
            import csv

            rows = list(csv.reader(file))

        assert rows[0] == ["id", "address", "timestamp", "connection", "direction", "data"]
        assert len(rows) == len(expected) + 1
        assert rows[1][1] == "@sensor.temp"
        assert rows[1][3] == "serial"

        json_path = tmp_path / "messages.json"
        command = Command(output=json_path)
        await command.put(engine.__manager__(Message).where().select())
        dumped = [json.loads(line) for line in json_path.read_text().splitlines()]
        assert dumped == expected
    finally:
        await engine.database.dispose()


def test_plain_json_output_gates_on_format_and_color() -> None:
    """The native path applies to any uncolored JSON dump, projected or not."""
    Command = create_entity_select_command(Message)

    assert Command().plain_json_output() in (True, False)
    assert Command(color=False).plain_json_output() is True
    assert Command(color=True).plain_json_output() is False
    assert Command(color=False, field="id").plain_json_output() is True
    assert Command(color=False, fields=["id"]).plain_json_output() is True
    from ceres.__internal__.cli.shared import CLIDataFormat

    assert Command(color=False, data_format=CLIDataFormat.CSV).plain_json_output() is False


def test_field_specs_resolve_as_whole_names() -> None:
    """A lone `--field` value is one spec, and flags override positional aliases by
    field name, never splitting into characters."""
    Command = create_entity_select_command(LogEntry)

    assert Command(field="level").resolved_fields() == {"level": "level"}
    assert Command(field="id:the id").resolved_fields() == {"id": "the id"}
    assert Command(fields=["content", "id:first"], field="id:last").resolved_fields() == {
        "content": "content",
        "id": "last",
    }
    assert Command().resolved_fields() is None


PROJECTIONS: dict[type, list[str]] = {
    Message: ["timestamp", "id:key", "data", "nonexistent", "connection"],
    Particle: ["data", "span", "type:kind", "id"],
    Alert: ["level", "type:type", "data", "id"],
    LogEntry: ["content:text", "level", "missing:gone"],
}


async def test_the_native_projected_dumps_match_the_materializing_path(tmp_path: Path) -> None:
    """A projected dump renders each field's wire value under its alias, byte-equal to
    extracting and writing every row in Python, for JSON and CSV alike.

    The projections exercise aliases, reordering, unknown names, an unset `span`, and
    a message payload that is not valid UTF-8.
    """
    from ceres.__internal__.cli.shared import CLIDataFormat

    engine = await _build_engine_on_disk(tmp_path)
    await _write_records(engine)

    try:
        for Record, fields in PROJECTIONS.items():
            for data_format in (CLIDataFormat.JSON, CLIDataFormat.CSV):
                query = engine.__manager__(Record).where()
                Command = create_entity_select_command(Record)
                expected_path = tmp_path / f"{Record.__name__}.{data_format.value}"
                command = Command(output=expected_path, field=list(fields))
                await command.put(engine.__manager__(Record).where().select())

                dumped = await dump_records_natively(
                    engine.database, Record, query, data_format, command.resolved_fields()
                )
                assert dumped is not None, f"expected a native dump for {Record.__name__}"
                assert dumped == expected_path.read_bytes().decode(), (
                    f"{Record.__name__} {data_format}"
                )
    finally:
        await engine.database.dispose()


async def test_an_empty_table_still_writes_the_csv_header(tmp_path: Path) -> None:
    """A CSV select matching no records still writes its header row, in both the
    native and the materializing paths, so the output always carries its schema."""
    from ceres.__internal__.cli.shared import CLIDataFormat

    engine = await _build_engine_on_disk(tmp_path)
    all_fields = {name: name for name in Alert.__pydantic_fields__}

    try:
        query = engine.__manager__(Alert).where()
        header = "id,address,timestamp,level,type,data\n"
        assert (
            await dump_records_natively(engine.database, Alert, query, CLIDataFormat.CSV) == header
        )
        assert (
            await dump_records_natively(
                engine.database, Alert, query, CLIDataFormat.CSV, {"id": "id", "level": "severity"}
            )
            == "id,severity\n"
        )
        assert await dump_records_natively(engine.database, Alert, query) == ""

        # The materializing path writes the same header through the select command's
        # all-fields projection.
        Command = create_entity_select_command(Alert)
        path = tmp_path / "empty.csv"
        command = Command(output=path)
        await command.put(query.select(), fields=all_fields)
        assert path.read_text() == header

        # `--no-header` leaves an empty result completely empty.
        bare_path = tmp_path / "empty-bare.csv"
        command = Command(output=bare_path, header=False)
        await command.put(query.select(), fields=all_fields)
        assert bare_path.read_text() == ""
        assert (
            await dump_records_natively(
                engine.database, Alert, query, CLIDataFormat.CSV, header=False
            )
            == ""
        )
    finally:
        await engine.database.dispose()


async def test_no_header_dumps_carry_only_data_rows(tmp_path: Path) -> None:
    """`--no-header` suppresses the CSV header row in both paths, projected or not,
    and the rows still match byte for byte."""
    from ceres.__internal__.cli.shared import CLIDataFormat

    engine = await _build_engine_on_disk(tmp_path)
    await _write_records(engine)

    try:
        for fields in (None, ["id", "timestamp:when"]):
            query = engine.__manager__(Message).where()
            Command = create_entity_select_command(Message)
            suffix = "projected" if fields else "full"
            path = tmp_path / f"bare-{suffix}.csv"
            command = Command(output=path, header=False, field=fields)
            await command.put(query.select())

            dumped = await dump_records_natively(
                engine.database,
                Message,
                query,
                CLIDataFormat.CSV,
                command.resolved_fields(),
                header=False,
            )
            assert dumped is not None
            assert dumped == path.read_bytes().decode()
            assert not dumped.startswith("id,")
    finally:
        await engine.database.dispose()


async def test_projected_message_data_renders_the_wire_text(tmp_path: Path) -> None:
    """A projected `data` field carries the record's latin-1 wire text, so a payload
    that is not valid UTF-8 still dumps."""
    engine = await _build_engine_on_disk(tmp_path)
    await _write_records(engine)

    try:
        query = engine.__manager__(Message).where(Message.Filter(connection="serial"))
        dumped = await dump_records_natively(
            engine.database, Message, query, fields={"data": "data", "span": "span"}
        )
        assert dumped == '{"data":"\\u0001\\u0002ABCÿ","span":null}\n'

        Command = create_entity_select_command(Message)
        json_path = tmp_path / "data.json"
        command = Command(output=json_path, field=["data", "span"])
        await command.put(query.select())
        assert json_path.read_bytes().decode() == dumped
    finally:
        await engine.database.dispose()
