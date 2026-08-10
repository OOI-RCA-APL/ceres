"""The native filter compiler's Python surface.

The compiler parses a filter once, compiles it per dialect, and the Python session
executes the statement through its own driver so these tests prove the compiled SQL
and its parameters round-trip through every backend's driver exactly as the query
layer's own statements do.
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from ceres import Engine
from ceres.__internal__.core import NativeFilter
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
    if engine.database._reader() is None:
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
    """Run a compiled listing on the store and return the row IDs."""
    rows = await engine.database._store().fetch(sql, parameters, "messages")
    return [str(row["id"]) for row in rows]


async def _scalar(engine: Engine, sql: str, parameters: list[Any]) -> Any:
    """The single value a compiled count or existence check returns."""
    rows = await engine.database._store().fetch(sql, parameters)
    return next(iter(rows[0].values()))


async def test_a_compiled_statement_answers_what_the_manager_does(tmp_path: Path) -> None:
    """Running the compiled SQL directly reaches the same rows the manager API reports.

    The manager compiles through here too so this is not two implementations agreeing.
    It is the compiled text being executable and meaning what the surface above it says,
    which a caller handed the SQL by `compiled` relies on.
    """
    engine = await _build_engine(tmp_path)
    await _seed(engine)
    dialect = engine.database.type.value

    try:
        for pairs in CASES:
            handle = NativeFilter.from_pairs("messages", pairs)
            filter = validate(Message.Filter, _fold(pairs))
            manager = engine.__manager__(Message)

            expected = [str(entity.id) for entity in await manager.where(filter)]
            sql, parameters = handle.compiled(dialect)
            assert await _execute(engine, sql, parameters) == expected, f"{pairs}"

            sql, parameters = handle.compiled(dialect, count=True)
            expected_count = await manager.where(filter).count()
            assert int(await _scalar(engine, sql, parameters)) == expected_count, f"count {pairs}"

            # The existence check answers what the `any` command reports. SQLite hands
            # back an integer where PostgreSQL hands back a boolean so compare on
            # truthiness rather than on the driver's type.
            sql, parameters = handle.exists_compiled(dialect)
            expected_any = await manager.where(filter).any()
            assert bool(await _scalar(engine, sql, parameters)) is expected_any, f"any {pairs}"
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
        handle = NativeFilter.from_json("messages", dumped)
        assert handle.limit == 3

        expected = [str(entity.id) for entity in await engine.__manager__(Message).where(filter)]
        sql, parameters = handle.compiled(dialect)
        assert await _execute(engine, sql, parameters) == expected
    finally:
        await engine.database.dispose()


def test_invalid_filters_raise_the_wire_message() -> None:
    with pytest.raises(ValueError, match="limit"):
        NativeFilter.from_pairs("messages", [("limit", "-1")])

    with pytest.raises(ValueError, match="or__"):
        NativeFilter.from_pairs("messages", [("or", '{"limit": 5}')])

    with pytest.raises(ValueError, match="native form"):
        NativeFilter.from_pairs("particles", [("class", "a.b:C")])


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
