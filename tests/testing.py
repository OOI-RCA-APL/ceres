import asyncio
import contextvars
from asyncio import sleep
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import UTC, datetime
from random import choice, randbytes, shuffle
from string import ascii_letters, printable
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from sqlalchemy import insert

from ceres import (
    Address,
    Alert,
    Entity,
    Group,
    GroupMembership,
    GroupPermission,
    Level,
    LogEntry,
    Message,
    MessageDirection,
    Particle,
    PermissionTargetType,
    Setting,
    User,
    UserPermission,
    Variable,
    utc,
)
from ceres.__internal__.auth import get_password_hash
from ceres.__internal__.entity import (
    BaseAddressEntityFilterArgs,
    BaseEntityFilterArgs,
    BaseUUIDEntityFilterArgs,
)
from ceres.__internal__.utilities.collections import group_by
from ceres.__internal__.utilities.randomize import randstr
from ceres.concurrency import awaitify
from ceres.config import BCryptHashingConfig, ComponentAccessLevel
from ceres.data import JSONDict, MaybeSequence, StrEnum, to_json, uuid7, validate
from ceres.database import Database
from ceres.timing import set_fake_now
from ceres.user import UserRole

if TYPE_CHECKING:
    from ceres.__internal__.record import BaseRecordFilterArgs
    from ceres.alert import AlertFilterArgs
    from ceres.item import Item
    from ceres.particle import ParticleFilterArgs
    from ceres.record import Record


async def wait_for_condition(
    description: str,
    condition: Callable[[], bool | Awaitable[bool]],
    timeout: float,
) -> None:
    start = utc()
    while True:
        if await awaitify(condition()):
            return
        if (utc() - start).total_seconds() >= timeout:
            raise TimeoutError(description)

        await sleep(0.05)


class FilterTest[TFilter: BaseEntityFilterArgs](TypedDict):
    filter: JSONDict
    keys: Sequence[str] | None
    update: NotRequired[JSONDict]


class FilterTestGroup[TFilter: BaseEntityFilterArgs](TypedDict):
    order: NotRequired[MaybeSequence[str] | None]
    entities: dict[str, dict[str, Any]]
    tests: list[FilterTest[TFilter]]


async def _iterate(executor: Any):
    output: list[Any] = []
    async with executor as results:
        async for entity in results:
            output.append(entity)


async def _get_first(executor: Any):
    async with executor as results:
        return await results.first()


async def _get_all(executor: Any):
    async with executor as results:
        return await results.all()


async def execute_filter_test(
    cls: type[Entity],
    group: FilterTestGroup,
    *,
    sort_key: Callable[[Any], Any] | None = None,
):
    order = group.get("order")
    entities: dict[str, Entity] = {}
    entity_inserts: list[Entity] = []
    for key, values in group["entities"].items():
        for entity in await arbitrary(cls, values):
            entity_inserts.append(entity)
            if isinstance(entity, cls):
                entities[key] = entity

    database = Database()
    await database.init()
    manager = cls.Manager(database)

    async def reset() -> None:
        await database.clear()
        async with database.session() as session:
            for group_cls, group in group_by(entity_inserts, type):
                shuffle(group)
                values = [entity.__entity_to_column_values__() for entity in group]
                await session.execute(insert(group_cls.Row).values(values))
                await session.commit()

    await reset()

    async def it(query: Any) -> list[Any]:
        async with query as results:
            return [result async for result in results]

    async def ifirst(query: Any) -> Any:
        async with query as results:
            return await results.first()

    async def iall(query: Any) -> list[Any]:
        async with query as results:
            return await results.all()

    async def run(test: FilterTest[BaseEntityFilterArgs]):
        Filter = cls.Filter

        filter_kwargs: Any = test["filter"]
        if order is not None and "order" not in filter_kwargs:
            filter_kwargs = {"order": order, **filter_kwargs}

        keys = test["keys"]
        update: Any = test.get("update", {})

        filter: Any = Filter.model_validate(filter_kwargs)
        expected = [entities[key] for key in keys] if keys is not None else list(entities.values())

        uexpected = unordered(expected)
        if sort_key is not None:
            expected.sort(key=sort_key)

        first = expected[0] if expected else None

        assert filter == Filter(**filter_kwargs)
        assert manager.where(filter) == manager.where(**filter_kwargs)
        assert manager.where(filter) == manager.where(**filter_kwargs)
        assert manager.where(filter).select() == manager.where(**filter_kwargs).select()
        assert manager.where(filter).delete() == manager.where(**filter_kwargs).delete()
        if update:
            assert manager.where(filter).update(update) == manager.where(**filter_kwargs).update(
                update
            )

        assert unordered(await manager.where(filter)) == unordered(expected)
        assert await manager.where(filter).select() == expected
        assert await manager.where(filter).count() == len(expected)
        assert bool(expected) == await manager.where(filter).any()
        assert await manager.where(filter).delete() == len(expected)
        assert await manager.where(filter) == []
        assert await manager.count() == len(entities) - len(expected)
        assert await manager.any() == bool(len(entities) - len(expected))
        await reset()
        if update:
            assert await manager.where(filter).update(update) == len(expected)
            await reset()

        assert await manager.where(filter).all() == expected
        assert await manager.where(filter).select().all() == expected
        assert unordered(await manager.where(filter).delete().all()) == uexpected
        assert await manager.where(filter) == []
        assert await manager.count() == len(entities) - len(expected)
        assert await manager.any() == bool(len(entities) - len(expected))
        await reset()
        if update:
            assert unordered(await manager.where(filter).update(update).all()) == uexpected
            await reset()

        assert await manager.where(filter).first() == first
        assert await manager.where(filter).select().first() == first
        assert await manager.where(filter).delete().first() == first
        assert await manager.where(filter) == expected[1:]
        assert await manager.count() == len(entities) - (1 if first is not None else 0)
        await reset()
        if update:
            assert await manager.where(filter).update(update).first() == first
            await reset()

        assert await it(manager.where(filter)) == expected
        assert await it(manager.where(filter).select()) == expected
        assert unordered(await it(manager.where(filter).delete())) == uexpected
        assert await manager.where(filter) == []
        assert await manager.count() == len(entities) - len(expected)
        await reset()
        if update:
            assert await it(manager.where(filter).update(update)) == uexpected
            await reset()

        assert await ifirst(manager.where(filter)) == first
        assert await ifirst(manager.where(filter).select()) == first
        if i_first := await ifirst(manager.where(filter).delete()):
            assert i_first in expected
        assert await manager.where(filter) == []
        assert await manager.count() == len(entities) - len(expected)
        await reset()

        if update:
            if i_first := await ifirst(manager.where(filter).update(update)):
                assert i_first in expected
            await reset()

        assert await iall(manager.where(filter)) == expected
        assert await iall(manager.where(filter).select()) == expected
        assert unordered(await iall(manager.where(filter).delete())) == uexpected
        assert await manager.where(filter) == []
        assert await manager.count() == len(entities) - len(expected)
        await reset()
        if update:
            assert unordered(await iall(manager.where(filter).update(update))) == uexpected
            await reset()

        slice_start = filter.offset or 0
        slice_end = filter.limit if filter.limit is not None else len(entities)

        python_filtered = [current for current in expected if filter.matches(current)]
        python_filtered = python_filtered[slice_start:slice_end]
        assert python_filtered == expected

    for test in group["tests"]:
        await run(test)


def unordered(values: list[Any]) -> list[Any]:
    copy = values.copy()
    keys = [
        (i, getattr(current, "id", None) or to_json(current)) for i, current in enumerate(values)
    ]
    keys.sort(key=lambda x: x[1])
    indexes = [i for i, _ in keys]

    for i, _ in keys:
        j = indexes[i]
        copy[i] = values[j]

    return copy


async def arbitrary(cls: type[Entity], values: JSONDict) -> list[Entity]:
    if cls is Message:
        return [
            validate(
                cls,
                {
                    "address": Address.ROOT,
                    "direction": choice(list(MessageDirection)),
                    "data": randbytes(32),
                    **values,
                },
            )
        ]

    if cls is Particle or cls is Particle[Any]:
        return [
            validate(
                cls,
                {
                    "address": Address.ROOT,
                    "type": randstr(printable, 8),
                    "data": {},
                    **values,
                },
            )
        ]

    if cls is Alert:
        return [
            validate(
                cls,
                {
                    "address": Address.ROOT,
                    "level": choice(list(Level)),
                    "type": randstr(printable, 8),
                    **values,
                },
            )
        ]

    if cls is LogEntry:
        return [
            validate(
                cls,
                {
                    "address": Address.ROOT,
                    "level": choice(list(Level)),
                    "content": randstr(printable, 32),
                    **values,
                },
            )
        ]

    if cls is User:
        return [
            validate(
                cls,
                {
                    "username": randstr(ascii_letters, 8),
                    "email": "email@email.com",
                    "password": get_password_hash(
                        randstr(printable, 8),
                        BCryptHashingConfig(rounds=4),
                    ),
                    "role": choice(list(UserRole)),
                    "disabled": choice([True, False]),
                    **values,
                },
            )
        ]

    if cls is Variable:
        return [
            validate(
                cls,
                {
                    "address": Address.ROOT,
                    "name": randstr(printable, 8),
                    "value": 0,
                    **values,
                },
            )
        ]

    if cls is Setting:
        user_id = values.get("user_id") or str(uuid7())
        user = (await arbitrary(User, {"id": user_id}))[0]
        return [
            user,
            validate(
                cls,
                {
                    "user_id": user_id,
                    "name": randstr(printable, 8),
                    "value": 0,
                    **values,
                },
            ),
        ]

    if cls is Group:
        return [
            validate(
                cls,
                {
                    "name": randstr(ascii_letters, 8),
                    "description": "",
                    **values,
                },
            )
        ]

    if cls is GroupMembership:
        user_id = values.get("user_id") or str(uuid7())
        group_id = values.get("group_id") or str(uuid7())
        user = (await arbitrary(User, {"id": user_id}))[0]
        group = (await arbitrary(Group, {"id": group_id}))[0]
        return [
            user,
            group,
            validate(
                cls,
                {
                    "user_id": user_id,
                    "group_id": group_id,
                    **values,
                },
            ),
        ]

    if cls is UserPermission:
        user_id = values.get("user_id") or str(uuid7())
        user = (await arbitrary(User, {"id": user_id}))[0]
        return [
            user,
            validate(
                cls,
                {
                    "user_id": user_id,
                    "target_type": PermissionTargetType.COMPONENT,
                    "target": randstr(printable, 8),
                    "level": ComponentAccessLevel.VIEW,
                    **values,
                },
            ),
        ]

    if cls is GroupPermission:
        group_id = values.get("group_id") or str(uuid7())
        group = (await arbitrary(Group, {"id": group_id}))[0]
        return [
            group,
            validate(
                cls,
                {
                    "group_id": group_id,
                    "target_type": PermissionTargetType.COMPONENT,
                    "target": randstr(printable, 8),
                    "level": ComponentAccessLevel.VIEW,
                    **values,
                },
            ),
        ]

    raise ValueError(cls)


def isort[T](left: Iterable[T]) -> Iterable[T]:
    return sorted(left, key=lambda item: id(item))


async def fake_now[T](value: datetime, coroutine: Awaitable[T]) -> T:
    context = contextvars.copy_context()

    async def run() -> T:
        set_fake_now(value)
        try:
            result = await coroutine
        finally:
            set_fake_now(None)

        return result

    return await asyncio.create_task(run(), context=context)


async def execute_string_filter_test(
    cls: type[Entity],
    field: str,
    *,
    prefixed: bool = True,
    equals: bool = True,
    contains: bool = True,
    prefix: bool = True,
    suffix: bool = True,
):
    equals_field = field
    contains_field = f"{field}_contains" if prefixed else "contains"
    prefix_field = f"{field}_prefix" if prefixed else "prefix"
    suffix_field = f"{field}_suffix" if prefixed else "suffix"

    group: FilterTestGroup[BaseEntityFilterArgs] = {
        "order": field,
        "entities": {
            "ABC": {field: "ABC"},
            "CBA": {field: "CBA"},
            "abc": {field: "abc"},
            "cba": {field: "cba"},
        },
        "tests": [
            {"filter": {}, "keys": None},
            # Equals
            *(
                [
                    {"filter": {equals_field: ""}, "keys": []},
                    {"filter": {equals_field: "abc"}, "keys": ["abc"]},
                    {"filter": {equals_field: ["abc"]}, "keys": ["abc"]},
                    {"filter": {equals_field: "cba"}, "keys": ["cba"]},
                    {"filter": {equals_field: "ABC"}, "keys": ["ABC"]},
                    {"filter": {equals_field: ["abc", "CBA"]}, "keys": ["CBA", "abc"]},
                ]
                if equals
                else []
            ),
            # Contains
            *(
                [
                    {"filter": {contains_field: ""}, "keys": None},
                    {"filter": {contains_field: []}, "keys": []},
                    {"filter": {contains_field: "ab"}, "keys": ["abc"]},
                    {"filter": {contains_field: ["ab"]}, "keys": ["abc"]},
                    {"filter": {contains_field: "ba"}, "keys": ["cba"]},
                    {"filter": {contains_field: ["ab", "ba"]}, "keys": ["abc", "cba"]},
                    {"filter": {contains_field: "A"}, "keys": ["ABC", "CBA"]},
                    {"filter": {contains_field: "CBA"}, "keys": ["CBA"]},
                    {"filter": {contains_field: ["", "CBA"]}, "keys": None},
                ]
                if contains
                else []
            ),
            # Prefix
            *(
                [
                    {"filter": {prefix_field: ""}, "keys": None},
                    {"filter": {prefix_field: []}, "keys": []},
                    {"filter": {prefix_field: "a"}, "keys": ["abc"]},
                    {"filter": {prefix_field: ["a"]}, "keys": ["abc"]},
                    {"filter": {prefix_field: "abc"}, "keys": ["abc"]},
                    {"filter": {prefix_field: "AB"}, "keys": ["ABC"]},
                    {"filter": {prefix_field: ["CB", "c"]}, "keys": ["CBA", "cba"]},
                    {"filter": {prefix_field: ["", "CBA"]}, "keys": None},
                ]
                if prefix
                else []
            ),
            # Suffix
            *(
                [
                    {"filter": {suffix_field: ""}, "keys": None},
                    {"filter": {suffix_field: []}, "keys": []},
                    {"filter": {suffix_field: "c"}, "keys": ["abc"]},
                    {"filter": {suffix_field: "abc"}, "keys": ["abc"]},
                    {"filter": {suffix_field: ["abc"]}, "keys": ["abc"]},
                    {"filter": {suffix_field: "BC"}, "keys": ["ABC"]},
                    {"filter": {suffix_field: ["BA", "a"]}, "keys": ["CBA", "cba"]},
                    {"filter": {suffix_field: ["", "CBA"]}, "keys": None},
                ]
                if suffix
                else []
            ),
        ],
    }

    await execute_filter_test(cls, group)


async def execute_email_filter_test(
    cls: type[Entity],
    field: str,
    *,
    equals: bool = True,
    contains: bool = True,
    prefix: bool = True,
    suffix: bool = True,
):
    equals_field = field
    contains_field = f"{field}_contains"
    prefix_field = f"{field}_prefix"
    suffix_field = f"{field}_suffix"

    group: FilterTestGroup[BaseEntityFilterArgs] = {
        "order": field,
        "entities": {
            "jake": {field: "jake@jake.com"},
            "john": {field: "JOHN@JOHN.ORG"},
            "nancy": {field: "NANCY@nancy.email.com"},
            "sarah": {field: "sarah@sarah.io"},
        },
        "tests": [
            {"filter": {}, "keys": None},
            # Equals
            {"filter": {equals_field: []}, "keys": []},
            {"filter": {equals_field: "none@none.com"}, "keys": []},
            {"filter": {equals_field: "jake@jake.com"}, "keys": ["jake"]},
            {"filter": {equals_field: "JAKE@JAKE.COM"}, "keys": ["jake"]},
            {"filter": {equals_field: "john@john.org"}, "keys": ["john"]},
            {"filter": {equals_field: ["JAKE@JAKE.com"]}, "keys": ["jake"]},
            {
                "filter": {equals_field: ["sarah@SARAH.io", "nancy@nancy.EmAiL.com"]},
                "keys": ["nancy", "sarah"],
            },
            # Contains
            {"filter": {contains_field: ""}, "keys": None},
            {"filter": {contains_field: "@"}, "keys": None},
            {"filter": {contains_field: []}, "keys": []},
            {"filter": {contains_field: "none"}, "keys": []},
            {"filter": {contains_field: "ake"}, "keys": ["jake"]},
            {"filter": {contains_field: "AKE"}, "keys": ["jake"]},
            {"filter": {contains_field: ["AKE"]}, "keys": ["jake"]},
            {"filter": {contains_field: ".co"}, "keys": ["jake", "nancy"]},
            {"filter": {contains_field: ".CO"}, "keys": ["jake", "nancy"]},
            {"filter": {contains_field: [".co", ".CO"]}, "keys": ["jake", "nancy"]},
            {"filter": {contains_field: ["Jake", "RaH"]}, "keys": ["jake", "sarah"]},
            # Prefix
            {"filter": {prefix_field: ""}, "keys": None},
            {"filter": {prefix_field: []}, "keys": []},
            {"filter": {prefix_field: ["none"]}, "keys": []},
            {"filter": {prefix_field: "jake"}, "keys": ["jake"]},
            {"filter": {prefix_field: "JAKE"}, "keys": ["jake"]},
            {"filter": {prefix_field: ["JAKE"]}, "keys": ["jake"]},
            {"filter": {prefix_field: "j"}, "keys": ["jake", "john"]},
            {"filter": {prefix_field: "J"}, "keys": ["jake", "john"]},
            {"filter": {prefix_field: ["j", "J"]}, "keys": ["jake", "john"]},
            {"filter": {prefix_field: ["nancy@NAN", "sAr"]}, "keys": ["nancy", "sarah"]},
            # # Suffix
            {"filter": {suffix_field: ""}, "keys": None},
            {"filter": {suffix_field: []}, "keys": []},
            {"filter": {suffix_field: ["none"]}, "keys": []},
            {"filter": {suffix_field: "jake.com"}, "keys": ["jake"]},
            {"filter": {suffix_field: "JAKE.COM"}, "keys": ["jake"]},
            {"filter": {suffix_field: ["JAKE.COM"]}, "keys": ["jake"]},
            {"filter": {suffix_field: ".com"}, "keys": ["jake", "nancy"]},
            {"filter": {suffix_field: [".org", ".io"]}, "keys": ["john", "sarah"]},
        ],
    }

    await execute_filter_test(cls, group)


async def execute_address_filter_test(cls: type[Item]):
    group: FilterTestGroup[BaseAddressEntityFilterArgs] = {
        "entities": {
            "@": {"address": "@"},
            "@abc": {"address": "@abc"},
            "@abc.cde": {"address": "@abc.cde"},
            "@abc.cde.efg": {"address": "@abc.cde.efg"},
            "@cde": {"address": "@cde"},
            "~": {"address": "~"},
        },
        "tests": [
            {"filter": {}, "keys": None},
            {"filter": {"address": "@none"}, "keys": []},
            {"filter": {"address": "@none:all"}, "keys": []},
            {"filter": {"address": "none"}, "keys": []},
            {"filter": {"address": "none:all"}, "keys": []},
            {"filter": {"address": "~"}, "keys": ["~"]},
            {"filter": {"address": "@"}, "keys": ["@"]},
            {"filter": {"address": "@abc"}, "keys": ["@abc"]},
            {"filter": {"address": "@abc.cde"}, "keys": ["@abc.cde"]},
            {"filter": {"address": ["@", "@cde"]}, "keys": ["@", "@cde"]},
            {"filter": {"address": "~:all"}, "keys": None},
            {
                "filter": {"address": "@:all"},
                "keys": ["@", "@abc", "@abc.cde", "@abc.cde.efg", "@cde"],
            },
            {"filter": {"address": "~:all|@:all"}, "keys": None},
            # {"filter": {"address": "all"}, "keys": None}, # TODO: Fix bare all.
            {"filter": {"address": "@abc:all"}, "keys": ["@abc", "@abc.cde", "@abc.cde.efg"]},
            {"filter": {"address": "abc:all"}, "keys": ["@abc", "@abc.cde", "@abc.cde.efg"]},
            {"filter": {"address": "@abc.cde:all"}, "keys": ["@abc.cde", "@abc.cde.efg"]},
            {"filter": {"address": "@abc.cde.efg:all"}, "keys": ["@abc.cde.efg"]},
        ],
    }

    await execute_filter_test(cls, group)


async def execute_enum_filter_test(
    cls: type[Entity],
    field: str,
    enum: type[StrEnum],
    *,
    comparison: bool = False,
):
    options = list(enum)

    group: FilterTestGroup[BaseEntityFilterArgs] = {
        "order": field,
        "entities": {value: {field: value} for value in options},
        "tests": [
            {"filter": {}, "keys": None},
            {"filter": {field: []}, "keys": []},
        ],
    }

    for i, value in enumerate(options):
        group["tests"].extend(
            [
                {"filter": {field: value}, "keys": [value]},
                {"filter": {field: [value]}, "keys": [value]},
            ]
        )

        previous = options[i - 1] if i > 0 else None
        if previous is not None:
            group["tests"].append(
                {"filter": {field: [previous, value]}, "keys": [previous, value]},
            )

    if comparison and len(options) > 1:
        first = options[0]
        second = options[1]
        second_last = options[-2]
        last = options[-1]

        group["tests"].extend(
            [
                {"filter": {f"min_{field}": None}, "keys": None},
                {"filter": {f"min_{field}": first}, "keys": None},
                {"filter": {f"min_{field}": second_last}, "keys": options[-2:]},
                {"filter": {f"min_{field}": last}, "keys": [last]},
                {"filter": {f"max_{field}": None}, "keys": None},
                {"filter": {f"max_{field}": first}, "keys": options[:1]},
                {"filter": {f"max_{field}": second}, "keys": options[:2]},
                {"filter": {f"max_{field}": last}, "keys": None},
            ]
        )

    await execute_filter_test(
        cls,
        group,
        sort_key=lambda entity: str(getattr(entity, field)),
    )


async def execute_boolean_filter_test(cls: type[Entity], field: str):
    group: FilterTestGroup[BaseEntityFilterArgs] = {
        "order": field,
        "entities": {
            "a": {field: False},
            "b": {field: True},
        },
        "tests": [
            {"filter": {}, "keys": None},
            {"filter": {field: None}, "keys": None},
            {"filter": {field: False}, "keys": ["a"]},
            {"filter": {field: True}, "keys": ["b"]},
        ],
    }

    await execute_filter_test(cls, group)


async def execute_id_filter_test(cls: type[Entity], field: str = "id"):
    group: FilterTestGroup[BaseUUIDEntityFilterArgs] = {
        "order": field,
        "entities": {
            "a": {field: "00000000-0000-0000-0000-000000000000"},
            "b": {field: "00000000-0000-0000-0000-000000000001"},
            "c": {field: "00000000-0000-0000-0000-000000000002"},
            "d": {field: "00000000-0000-0000-0000-000000000003"},
        },
        "tests": [
            {"filter": {}, "keys": None},
            {"filter": {field: "00000000-0000-0000-0000-000000000000"}, "keys": ["a"]},
            {"filter": {field: "00000000-0000-0000-0000-000000000001"}, "keys": ["b"]},
            {"filter": {field: ["00000000-0000-0000-0000-000000000002"]}, "keys": ["c"]},
            {
                "filter": {
                    field: [
                        "00000000-0000-0000-0000-000000000002",
                        "00000000-0000-0000-0000-000000000003",
                    ]
                },
                "keys": ["c", "d"],
            },
        ],
    }

    await execute_filter_test(cls, group)


async def execute_json_data_filter_test(cls: type[Particle | Alert], field: str):
    contains_field = f"{field}_contains"
    prefix_field = f"{field}_prefix"
    suffix_field = f"{field}_suffix"

    group: FilterTestGroup[ParticleFilterArgs | AlertFilterArgs] = {
        "entities": {
            "a": {field: {"number": 123, "name": "abc"}},
            "b": {field: {"number": 345, "name": "cba"}},
            "c": {field: {"NAME": "ABC", "NUMBERS": [123]}},
            "d": {field: {"NAME": "CBA", "NUMBERS": [345]}},
        },
        "tests": [
            {"filter": {}, "keys": None},
            # Contains
            {"filter": {contains_field: ""}, "keys": None},
            {"filter": {contains_field: []}, "keys": []},
            {"filter": {contains_field: "abc"}, "keys": ["a"]},
            {"filter": {contains_field: '"abc"'}, "keys": ["a"]},
            {"filter": {contains_field: "ABC"}, "keys": ["c"]},
            {"filter": {contains_field: '"ABC",'}, "keys": ["c"]},
            {"filter": {contains_field: '"name":'}, "keys": ["a", "b"]},
            {"filter": {contains_field: '"NUMBERS":'}, "keys": ["c", "d"]},
            {"filter": {contains_field: "123"}, "keys": ["a", "c"]},
            {"filter": {contains_field: "[123]"}, "keys": ["c"]},
            {"filter": {contains_field: ["123", ':"cba"']}, "keys": ["a", "b", "c"]},
            # Prefix
            {"filter": {prefix_field: ""}, "keys": None},
            {"filter": {prefix_field: []}, "keys": []},
            {"filter": {prefix_field: "none"}, "keys": []},
            {"filter": {prefix_field: "{"}, "keys": None},
            {"filter": {prefix_field: '{"number":123,'}, "keys": ["a"]},
            {"filter": {prefix_field: '{"number"'}, "keys": ["a", "b"]},
            {"filter": {prefix_field: '{"NAME":'}, "keys": ["c", "d"]},
            {"filter": {prefix_field: '{"NAME":'}, "keys": ["c", "d"]},
            {"filter": {prefix_field: "number"}, "keys": []},
            {"filter": {prefix_field: "NUMBERS"}, "keys": []},
            {"filter": {prefix_field: ['{"number"', '{"NAME":"CBA"']}, "keys": ["a", "b", "d"]},
            # Suffix
            {"filter": {suffix_field: ""}, "keys": None},
            {"filter": {suffix_field: []}, "keys": []},
            {"filter": {suffix_field: "none"}, "keys": []},
            {"filter": {suffix_field: "}"}, "keys": None},
            {"filter": {suffix_field: ',"name":"abc"}'}, "keys": ["a"]},
            {"filter": {suffix_field: "]}"}, "keys": ["c", "d"]},
            {"filter": {suffix_field: ',"NUMBERS":[123]}'}, "keys": ["c"]},
            {"filter": {suffix_field: ',"NUMBERS":[345]}'}, "keys": ["d"]},
            {"filter": {suffix_field: "number"}, "keys": []},
            {"filter": {suffix_field: "NUMBERS"}, "keys": []},
            {"filter": {suffix_field: ['"name":"abc"}', ',"NUMBERS":[345]}']}, "keys": ["a", "d"]},
        ],
    }

    await execute_filter_test(cls, group)


async def execute_timestamp_filter_test(cls: type[Record]):
    group: FilterTestGroup[BaseRecordFilterArgs] = {
        "entities": {
            "a": {"timestamp": "2024-01-01T00:00:00Z"},
            "b": {"timestamp": "2024-01-02T00:00:00Z"},
            "c": {"timestamp": "2024-01-03T00:00:00Z"},
            "d": {"timestamp": "2024-01-04T00:00:00Z"},
        },
        "tests": [
            {"filter": {}, "keys": None},
            {"filter": {"timestamp": []}, "keys": []},
            {"filter": {"timestamp": "2024-01-01T00:00:00Z"}, "keys": ["a"]},
            {"filter": {"timestamp": "2024-01-02T00:00:00Z"}, "keys": ["b"]},
            {"filter": {"timestamp": ["2024-01-03T00:00:00Z"]}, "keys": ["c"]},
            {
                "filter": {"timestamp": ["2024-01-01T00:00:00Z", "2024-01-03T00:00:00Z"]},
                "keys": ["a", "c"],
            },
        ],
    }

    await execute_filter_test(cls, group)

    group = {
        "entities": {
            "a": {"timestamp": "2024-01-01T00:00:00Z"},
            "b": {"timestamp": "2024-01-01T00:01:00Z"},
            "c": {"timestamp": "2024-01-01T01:00:00Z"},
            "d": {"timestamp": "2024-01-01T12:00:00Z"},
            "e": {"timestamp": "2024-01-02T00:00:00Z"},
        },
        "tests": [
            {"filter": {}, "keys": None},
            # Before
            {"filter": {"before": "2024-01-01T01:00:00Z"}, "keys": ["a", "b"]},
            {"filter": {"before": "2024-01-01T00:01:00Z"}, "keys": ["a"]},
            {"filter": {"before": "2024-03-01T00:00:00Z"}, "keys": None},
            # After
            {"filter": {"after": "2024-01-01T00:00:00Z"}, "keys": None},
            {"filter": {"after": "2024-01-01T00:01:00Z"}, "keys": ["b", "c", "d", "e"]},
            {"filter": {"after": "2024-01-01T01:00:00Z"}, "keys": ["c", "d", "e"]},
            {"filter": {"after": "2024-03-01T00:00:00Z"}, "keys": []},
            # Before and After
            {
                "filter": {"after": "2024-01-01T00:00:01Z", "before": "2024-01-02T00:00:00Z"},
                "keys": ["b", "c", "d"],
            },
            # Timespan After and Before
            {"filter": {"after": "2024-01-01T00:00:05Z", "timespan": "2h"}, "keys": ["b", "c"]},
            {
                "filter": {"before": "2024-01-02T00:00:00Z", "timespan": "23h"},
                "keys": ["c", "d"],
            },
        ],
    }

    await execute_filter_test(cls, group)

    group = {
        "entities": {
            "a": {"timestamp": "2024-01-01T00:00:00Z"},
            "b": {"timestamp": "2024-01-02T00:00:00Z"},
            "c": {"timestamp": "2024-01-03T00:00:00Z"},
            "d": {"timestamp": "2024-01-04T00:00:00Z"},
            "e": {"timestamp": "2024-01-05T00:00:00Z"},
        },
        "tests": [
            {"filter": {}, "keys": None},
            # Min Age
            {"filter": {"min_age": 0}, "keys": ["a", "b", "c"]},
            {"filter": {"min_age": "1d"}, "keys": ["a", "b"]},
            {"filter": {"min_age": "1.5d"}, "keys": ["a"]},
            {"filter": {"min_age": "2d"}, "keys": ["a"]},
            {"filter": {"min_age": "3d"}, "keys": []},
            # # Max Age
            {"filter": {"max_age": "1d"}, "keys": ["c", "d", "e"]},
            {"filter": {"max_age": "1.5d"}, "keys": ["b", "c", "d", "e"]},
            {"filter": {"max_age": "2d"}, "keys": ["b", "c", "d", "e"]},
            {"filter": {"max_age": "3d"}, "keys": None},
        ],
    }

    await fake_now(
        datetime(year=2024, month=1, day=3, tzinfo=UTC),
        execute_filter_test(cls, group),
    )

    group: FilterTestGroup[BaseRecordFilterArgs] = {
        "entities": {
            "a": {"timestamp": "2024-01-01T00:00:00Z"},
            "b": {"timestamp": "2024-01-01T01:00:00Z"},
            "c": {"timestamp": "2024-01-01T02:00:00Z"},
            "d": {"timestamp": "2024-01-01T03:00:00Z"},
        },
        "tests": [
            {"filter": {}, "keys": None},
            # After Hour
            {"filter": {"after_hour": 0}, "keys": None},
            {"filter": {"after_hour": 2}, "keys": ["c", "d"]},
            {"filter": {"after_hour": 4}, "keys": []},
            # Before Hour
            {"filter": {"before_hour": 3}, "keys": ["a", "b", "c"]},
            {"filter": {"before_hour": 4}, "keys": None},
            {"filter": {"before_hour": 24}, "keys": None},
            # After and Before Hour
            {"filter": {"after_hour": 0, "before_hour": 24}, "keys": None},
            {"filter": {"after_hour": 1, "before_hour": 3}, "keys": ["b", "c"]},
            {"filter": {"after_hour": 3, "before_hour": 1}, "keys": ["a", "d"]},
        ],
    }

    await execute_filter_test(cls, group)

    group: FilterTestGroup[BaseRecordFilterArgs] = {
        "entities": {
            "a": {"timestamp": "2024-01-01T00:00:00Z"},
            "b": {"timestamp": "2024-01-01T00:01:00Z"},
            "c": {"timestamp": "2024-01-01T00:02:00Z"},
            "d": {"timestamp": "2024-01-01T00:03:00Z"},
        },
        "tests": [
            {"filter": {}, "keys": None},
            # After Minute
            {"filter": {"after_minute": 0}, "keys": None},
            {"filter": {"after_minute": 2}, "keys": ["c", "d"]},
            {"filter": {"after_minute": 4}, "keys": []},
            # Before Minute
            {"filter": {"after_minute": 0}, "keys": None},
            {"filter": {"before_minute": 3}, "keys": ["a", "b", "c"]},
            {"filter": {"before_minute": 4}, "keys": None},
            {"filter": {"before_minute": 60}, "keys": None},
            # After and Before Minute
            {"filter": {"after_minute": 0, "before_minute": 60}, "keys": None},
            {"filter": {"after_minute": 1, "before_minute": 3}, "keys": ["b", "c"]},
            {"filter": {"after_minute": 3, "before_minute": 1}, "keys": ["a", "d"]},
        ],
    }

    await execute_filter_test(cls, group)
