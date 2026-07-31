"""Parity between the native filter subset and the Python query layer.

Every vector here feeds the same wire pairs to both sides. The Python side folds them
into the Pydantic filter and executes through the query layer, the native side parses
them into the Rust subset and executes through the record store, and the two must
produce identical serialized records on every backend. Constructs outside the subset
must decline rather than guess, and the classification test holds the subset's key
lists to exactly the fields the Pydantic filters declare.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from ceres_core import (
    EntityTable,
    RecordTable,
    entity_filter_keys,
    parse_record_filter,
    record_filter_keys,
)

from ceres import Engine
from ceres.address import Address
from ceres.alert import Alert
from ceres.config import Config
from ceres.data import to_json, validate
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message, MessageDirection
from ceres.particle import Particle
from ceres.setting import Setting
from ceres.user import User
from ceres.variable import Variable
from ceres.workspace import Workspace

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.databases()
"""Every backend, the subset must compile each dialect identically to SQLAlchemy."""

RECORD_TABLES = {
    Message: RecordTable.MESSAGES,
    Particle: RecordTable.PARTICLES,
    Alert: RecordTable.ALERTS,
    LogEntry: RecordTable.LOGS,
}

ENTITY_TABLES = {
    User: EntityTable.USERS,
    Variable: EntityTable.VARIABLES,
    Setting: EntityTable.SETTINGS,
    Workspace: EntityTable.WORKSPACES,
}
"""The non-record entities the CLI manages, whose filter language is a strict subset."""

NOW = datetime.now(UTC).replace(microsecond=83155)
"""The anchor seeded timestamps offset from.

Age-based vectors compare against each side's own execution instant, so seeded offsets
sit hours from every age boundary and a few seconds of skew cannot recross one.
"""


async def _build_engine(tmp_path: Path) -> Engine:
    """Build an engine on the run's backend, on disk when the default cannot fetch natively."""
    engine = Engine()
    if engine.database._record_fetcher() is None:
        engine = Engine()
        await engine.load(
            validate(
                Config,
                {
                    "components": [],
                    "database": {"type": "sqlite", "path": str(tmp_path / "parity.sqlite")},
                },
            ),
            checks=(),
        )

    await engine.database.migrate()
    return engine


async def _seed(engine: Engine) -> None:
    """Write a dataset varied enough that every vector separates records."""
    sensor = Address("@sensor.temp")
    motor = Address("@motor")
    # A mixed-case name with an underscore exercises case-sensitive prefix matching
    # and wildcard escaping in the selector patterns.
    deck = Address("@Deck_upper.motor")

    for index, (address, offset) in enumerate(
        [
            (sensor, timedelta(hours=9)),
            (sensor, timedelta(hours=5)),
            (motor, timedelta(hours=5, minutes=30)),
            (motor, timedelta(minutes=45)),
            (deck, timedelta(hours=2)),
        ]
    ):
        # One whole-second timestamp exercises the fraction-free stored text form.
        timestamp = NOW - offset
        if index == 2:
            timestamp = timestamp.replace(microsecond=0)

        await engine.database.messages.create(
            Message.Create(
                address=address,
                timestamp=timestamp,
                connection="serial" if index % 2 == 0 else "network",
                direction=MessageDirection.RECEIVE if index % 2 == 0 else MessageDirection.SEND,
                data=bytes([index, 0x01, 0xFF]),
            )
        )
        await engine.database.particles.create(
            Particle.Create(
                address=address,
                timestamp=timestamp,
                type="sample" if index % 2 == 0 else "sweep",
                data={"index": index, "values": [1.5, 2.5]},
            )
        )
        await engine.database.alerts.create(
            Alert.Create(
                address=address,
                timestamp=timestamp,
                level=[Level.DEBUG, Level.INFO, Level.WARNING, Level.CRITICAL, Level.INFO][index],
                type="overheat" if index % 2 == 0 else "stall",
                data={"index": index},
            )
        )
        await engine.database.logs.create(
            LogEntry.Create(
                address=address,
                timestamp=timestamp,
                level=[Level.DEBUG, Level.INFO, Level.ERROR, Level.CRITICAL, Level.INFO][index],
                content=f"entry {index}",
            )
        )


def _fold(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Fold ordered pairs the way the operation layer does before validating."""
    data: dict[str, Any] = {}
    for name, value in pairs:
        if name not in data:
            data[name] = value
        elif isinstance(data[name], list):
            data[name].append(value)
        else:
            data[name] = [data[name], value]

    return data


def _timestamp_of(engine: Engine, index: int) -> str:
    """The wire text of one seeded timestamp, in RFC 3339 form."""
    offsets = [
        timedelta(hours=9),
        timedelta(hours=5),
        timedelta(hours=5, minutes=30),
        timedelta(minutes=45),
        timedelta(hours=2),
    ]
    timestamp = NOW - offsets[index]
    if index == 2:
        timestamp = timestamp.replace(microsecond=0)

    return timestamp.isoformat().replace("+00:00", "Z")


VECTORS: dict[type[Any], list[list[tuple[str, str]]]] = {
    Message: [
        [],
        [("address", "@sensor.temp")],
        [("address", "@motor"), ("order", "timestamp:desc")],
        [("after", ""), ("timespan", "3h")],
        [("timespan", "6h")],
        [("max_age", "2h")],
        [("min_age", "4h")],
        [("min_age", "1h"), ("max_age", "8h")],
        [("connection", "serial")],
        [("connection", "serial"), ("connection", "network")],
        [("direction", "send")],
        [("order", "address:desc"), ("order", "timestamp")],
        [("order", "connection")],
        [("limit", "2")],
        [("limit", "2"), ("offset", "1")],
        [("offset", "1")],
        [("limit", "0")],
        [("connection_contains", "eri")],
        [("connection_prefix", "net"), ("connection_suffix", "work")],
        [("contains", "\x01")],
        [("prefix", "\x00")],
        [("suffix", "\xff")],
        [("contains", ""), ("contains", "\x01")],
        [("data", "\x01\x01\xff")],
        [("data", "\x00\x01\xff"), ("data", "\x02\x01\xff")],
        [("order", "data:desc"), ("limit", "2")],
        [("contains", "%")],
        [("contains", "*")],
        [("address", "@sensor:children")],
        [("address", "@sensor:descendants")],
        [("address", "@sensor:all")],
        [("address", "@sensor.temp|@motor")],
        [("address", "@motor"), ("address", "@sensor:descendants")],
        [("address", "~:descendants")],
        [("address", "@:children")],
        [("address", "all")],
        [("root", "@sensor"), ("address", ":children")],
        [("root", "@sensor"), ("address", "temp")],
        [("address", "@Deck_upper:children")],
        [("address", "@deck_upper:children")],
        [("address", "@Deck_upper.motor")],
        [("timespan", "PT6H")],
        [("max_age", "PT2H30M")],
        [("timespan", "21600")],
        [("after_hour", "0")],
        [("after_hour", "24")],
        [("after_hour", "9"), ("before_hour", "17")],
        [("after_hour", "22"), ("before_hour", "3")],
        [("before_minute", "30")],
        [("after_minute", "45"), ("before_minute", "10")],
        [("after", "$epoch")],
        [("after", "$date")],
        [
            ("or", '{"connection": "network", "direction": "receive"}'),
            ("connection", "serial"),
            ("direction", "send"),
        ],
        [("or", '{"connection": "network"}'), ("or", '{"direction": "receive"}')],
        [("or", '[{"connection": "serial"}, {"address": "@motor"}]')],
        [("or", "{}"), ("connection", "serial")],
        [("or", '{"and": [{"connection": "network"}, {"direction": "send"}]}')],
        [("or", "{connection: network}")],
        [("or", '{"or": [{"connection": "serial"}]}')],
        [("or", '{"connection_contains": "eri"}'), ("or", '{"address": "@motor:all"}')],
        [("and", '{"after_hour": 0}'), ("connection", "serial")],
        [("and", '{"limit": 2, "order": "timestamp:desc"}')],
        [("limit", "3"), ("and", '{"limit": 5}')],
        [("and", '{"offset": 1}')],
        [("subsample_every", "3h"), ("after", "$date"), ("order", "timestamp:desc")],
    ],
    Particle: [
        [("subsample_every", "4h")],
        [("subsample_every", "2h"), ("after", "$date")],
        [("subsample_every", "90m"), ("after", ""), ("subsample_select", "last")],
        [("subsample", "4"), ("after", ""), ("timespan", "12h")],
        [("subsample", "3"), ("after", ""), ("timespan", "12h"), ("subsample_select", "last")],
        [("and", '{"subsample_every": "6h", "after": "2020-01-01T00:00:00Z"}')],
        [("type", "sample")],
        [("type", "sample"), ("type", "sweep"), ("order", "timestamp:desc"), ("limit", "3")],
        [("type_contains", "amp")],
        [("data_contains", "2.5")],
        [("data_prefix", "{")],
    ],
    Alert: [
        [("or", '{"min_level": "error"}'), ("type", "overheat")],
        [("and", '{"type_suffix": "eat"}'), ("order", "level:desc")],
        [("level", "warning")],
        [("min_level", "warning")],
        [("max_level", "info")],
        [("min_level", "info"), ("max_level", "error")],
        [("type", "overheat"), ("order", "level")],
        [("type_contains", "eat")],
        [("type_prefix", "over")],
        [("type_suffix", "all")],
        [("data_contains", "index")],
        [("data_contains", "index"), ("min_level", "info")],
    ],
    LogEntry: [
        [("level", "error"), ("level", "critical")],
        [("min_level", "error")],
        [("content", "entry 1")],
        [("contains", "entry")],
        [("prefix", "entry")],
        [("suffix", "1")],
        [("contains", "y 1")],
        [("contains", "y_1")],
        [("contains", "*")],
        [("contains", "%")],
        [("contains", "")],
        [("contains", ""), ("contains", "1")],
        [("content", "entry 0"), ("suffix", "0")],
    ],
}
"""The shared vectors, plus per-table ones. An `after` value of `""` is filled in with a
seeded timestamp at run time, so the vector table stays static."""


def _resolve(engine: Engine, pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    resolved = []
    for name, value in pairs:
        if name in ("after", "before", "timestamp") and value == "":
            value = _timestamp_of(engine, 1)

        if value == "$epoch":
            value = str((NOW - timedelta(hours=5)).timestamp())

        if value == "$date":
            value = NOW.date().isoformat()

        resolved.append((name, value))

    return resolved


async def test_the_native_subset_matches_the_query_layer(tmp_path: Path) -> None:
    """Every supported vector produces byte-identical records through both compilers."""
    engine = await _build_engine(tmp_path)
    await _seed(engine)
    fetcher = engine.database._record_fetcher()
    assert fetcher is not None

    try:
        for Record, vectors in VECTORS.items():
            table = RECORD_TABLES[Record]
            for pairs in vectors:
                pairs = _resolve(engine, pairs)
                filter = validate(Record.Filter, _fold(pairs))

                expected = [
                    json.loads(to_json(entity))
                    for entity in await engine.__manager__(Record).where(filter)
                ]
                awaitable = fetcher.fetch_pairs(table, pairs)
                assert awaitable is not None, f"{Record.__name__} declined {pairs}"
                native = json.loads((await awaitable).to_json())
                assert native == expected, f"{Record.__name__} diverged on {pairs}"

                expected_count = await engine.__manager__(Record).where(filter).count()
                counting = fetcher.count_pairs(table, pairs)
                assert counting is not None
                assert await counting == expected_count, f"count diverged on {pairs}"

                # The native matcher must read each record the way the Python filter's
                # in-memory matching does.
                handle = parse_record_filter(table, pairs)
                for entity in await engine.__manager__(Record).where(Record.Filter()):
                    record_json = to_json(entity)
                    assert handle.matches(record_json) == filter.matches(entity), (
                        f"{Record.__name__} match diverged on {pairs} for {record_json}"
                    )
    finally:
        await engine.database.dispose()


async def test_exact_timestamps_match_in_both_stored_precisions(tmp_path: Path) -> None:
    """Whole-second and microsecond timestamps both round-trip the stored text form."""
    engine = await _build_engine(tmp_path)
    await _seed(engine)
    fetcher = engine.database._record_fetcher()
    assert fetcher is not None

    try:
        for index in (1, 2):
            pairs = [("timestamp", _timestamp_of(engine, index))]
            filter = validate(Message.Filter, _fold(pairs))
            expected = [
                json.loads(to_json(entity))
                for entity in await engine.__manager__(Message).where(filter)
            ]
            assert expected, f"expected a seeded message at index {index}"

            awaitable = fetcher.fetch_pairs(RecordTable.MESSAGES, pairs)
            assert awaitable is not None
            assert json.loads((await awaitable).to_json()) == expected
    finally:
        await engine.database.dispose()


async def test_constructs_outside_the_subset_decline(tmp_path: Path) -> None:
    """Delegated keys, malformed values, and selector addresses all answer `None`."""
    engine = await _build_engine(tmp_path)
    fetcher = engine.database._record_fetcher()
    assert fetcher is not None

    try:
        for pairs in [
            [("subsample", "10")],
            [("address", "@a,@b")],
            [("or", '{"limit": 5}')],
            [("or", "not: [valid")],
            [("after", "yesterday")],
            [("timespan", "-PT5S")],
            [("after_hour", "25")],
            [("unknown", "1")],
        ]:
            assert fetcher.fetch_pairs(RecordTable.MESSAGES, pairs) is None, f"{pairs}"
            assert fetcher.count_pairs(RecordTable.MESSAGES, pairs) is None, f"{pairs}"
    finally:
        await engine.database.dispose()


def _declared_keys(Entity: Any) -> set[str]:
    """The wire keys an entity's Pydantic filter declares."""
    return {field.serialization_alias or name for name, field in Entity.Filter.model_fields.items()}


def test_every_filter_field_is_classified() -> None:
    """The native key lists cover the Pydantic filters exactly, so new fields cannot
    ship unclassified.
    """
    for Record, table in RECORD_TABLES.items():
        supported, delegated = record_filter_keys(table)
        assert not set(supported) & set(delegated)
        assert set(supported) | set(delegated) == _declared_keys(Record), Record.__name__

    for Entity, entity_table in ENTITY_TABLES.items():
        supported, delegated = entity_filter_keys(entity_table)
        assert not set(supported) & set(delegated)
        assert set(supported) | set(delegated) == _declared_keys(Entity), Entity.__name__


def test_the_entity_grammar_is_a_subset_of_the_record_one() -> None:
    """No entity filter key exists that the record grammar has no notion of.

    The Python entity filters descend from the same base the record ones extend, so a
    key appearing here that no record table declares would mean a second grammar had
    grown, which is the thing the shared compiler exists to prevent.
    """
    record_keys: set[str] = set()
    for record_table in RECORD_TABLES.values():
        supported, delegated = record_filter_keys(record_table)
        record_keys |= set(supported) | set(delegated)

    # Every key an entity brings is either shared with a record table or names one of
    # that entity's own columns, never a construct the record grammar lacks.
    constructs = {"order", "limit", "offset", "or", "and", "root", "address"}
    for Entity, table in ENTITY_TABLES.items():
        supported, delegated = entity_filter_keys(table)
        columns = set(Entity.__entity_columns__)
        for key in set(supported) | set(delegated):
            base = key.rsplit("_", 1)[0]
            assert (
                key in record_keys
                or key in constructs
                or key in columns
                or base in columns
                # A computed predicate has no column of its own, matching a shape of
                # one instead.
                or key in {"internal", "placed_on_engine", "owned"}
            ), f"{Entity.__name__} brings {key!r}, which the record grammar has no form of"
