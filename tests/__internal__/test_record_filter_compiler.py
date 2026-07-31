"""The native filter compiler's Python surface.

The compiler parses a filter once, compiles it per dialect, and the Python session
executes the statement through its own driver, so these tests prove the compiled SQL
and its parameters round-trip through every backend's driver exactly as the query
layer's own statements do.
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from ceres_core import RecordTable, parse_record_filter, record_filter_from_json

from ceres import Engine
from ceres.address import Address
from ceres.config import Config
from ceres.data import validate
from ceres.message import Message, MessageDirection

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.databases()
"""Every backend, the compiled parameters must bind through each driver."""

NOW = datetime.now(UTC).replace(microsecond=250000)


async def _build_engine(tmp_path: Path) -> Engine:
    engine = Engine()
    if engine.database._record_fetcher() is None:
        engine = Engine()
        await engine.load(
            validate(
                Config,
                {
                    "components": [],
                    "database": {"type": "sqlite", "path": str(tmp_path / "compiler.sqlite")},
                },
            ),
            checks=(),
        )

    await engine.database.migrate()
    return engine


async def _seed(engine: Engine) -> list[Message]:
    records = []
    for index in range(4):
        records.append(
            await engine.database.messages.create(
                Message.Create(
                    address=Address("@sensor.temp" if index % 2 == 0 else "@motor"),
                    timestamp=NOW - timedelta(hours=index),
                    connection="serial" if index % 2 == 0 else None,
                    direction=MessageDirection.SEND,
                    data=bytes([index]),
                )
            )
        )

    return records


CASES: list[list[tuple[str, str]]] = [
    [],
    [("address", "@sensor.temp")],
    [("connection", "serial"), ("order", "timestamp:desc")],
    [("or", '[{"connection": "serial"}, {"address": "@motor"}]')],
    [("after", (NOW - timedelta(hours=2, minutes=30)).isoformat()), ("limit", "2")],
    [("contains", "\x02")],
    [("limit", "2"), ("offset", "1")],
]


async def _execute(engine: Engine, sql: str, parameters: list[Any]) -> list[str]:
    """Run a compiled listing through the Python session and return the row IDs."""
    async with await engine.database.use() as connection:
        result = await connection.exec_driver_sql(sql, tuple(parameters))
        return [str(row._mapping["id"]) for row in result.fetchall()]


async def test_compiled_statements_execute_through_the_python_session(tmp_path: Path) -> None:
    engine = await _build_engine(tmp_path)
    await _seed(engine)
    dialect = engine.database.type.value

    try:
        for pairs in CASES:
            handle = parse_record_filter(RecordTable.MESSAGES, pairs)
            expected = [
                str(entity.id)
                for entity in await engine.__manager__(Message).where(
                    validate(Message.Filter, _fold(pairs))
                )
            ]

            sql, parameters = handle.compiled(dialect)
            assert await _execute(engine, sql, parameters) == expected, f"{pairs}"

            counting = validate(Message.Filter, _fold(pairs))
            expected_count = await engine.__manager__(Message).where(counting).count()
            sql, parameters = handle.compiled(dialect, count=True)
            async with await engine.database.use() as connection:
                result = await connection.exec_driver_sql(sql, tuple(parameters))
                row = result.fetchone()
                assert row is not None
                assert int(row[0]) == expected_count, f"count {pairs}"
    finally:
        await engine.database.dispose()


async def test_filters_parse_from_the_model_json_dump(tmp_path: Path) -> None:
    """The filter model's dump parses into the same statement the pairs form does."""
    engine = await _build_engine(tmp_path)
    await _seed(engine)
    dialect = engine.database.type.value

    try:
        filter = validate(
            Message.Filter,
            {
                "connection": "serial",
                "or": '{"address": "@motor"}',
                "order": "timestamp:desc",
                "limit": "3",
            },
        )
        dumped = filter.model_dump_json(by_alias=True, exclude_none=True)
        handle = record_filter_from_json(RecordTable.MESSAGES, dumped)
        assert handle.limit == 3

        expected = [str(entity.id) for entity in await engine.__manager__(Message).where(filter)]
        sql, parameters = handle.compiled(dialect)
        assert await _execute(engine, sql, parameters) == expected
    finally:
        await engine.database.dispose()


def test_invalid_filters_raise_the_wire_message() -> None:
    with pytest.raises(ValueError, match="limit"):
        parse_record_filter(RecordTable.MESSAGES, [("limit", "-1")])

    with pytest.raises(ValueError, match="or__"):
        parse_record_filter(RecordTable.MESSAGES, [("or", '{"limit": 5}')])

    with pytest.raises(ValueError, match="native form"):
        parse_record_filter(RecordTable.PARTICLES, [("class", "a.b:C")])


def _fold(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name, value in pairs:
        if name not in data:
            data[name] = value
        elif isinstance(data[name], list):
            data[name].append(value)
        else:
            data[name] = [data[name], value]

    return data
