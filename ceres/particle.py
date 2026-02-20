from __future__ import annotations

import builtins
import re
from abc import abstractmethod
from collections.abc import (
    Callable,
    ItemsView,
    Iterable,
    Iterator,
    KeysView,
    Mapping,
    MutableMapping,
    ValuesView,
)
from re import Pattern
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Literal,
    LiteralString,
    Self,
    TypeAlias,
    Unpack,
    overload,
    override,
)

from pydantic import ConfigDict, ImportString, SerializeAsAny, ValidationError, model_validator
from sqlalchemy import JSON, Index, Text, cast
from sqlalchemy.orm import Mapped, mapped_column

# Used for `TypeVar` default.
from typing_extensions import TypeVar

from ceres._internal import util
from ceres._internal.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    EntityNaming,
    EntityOutputChannel,
    EntityQuery,
    EntityTransform,
)
from ceres._internal.manager import BaseNodeManager
from ceres._internal.record import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordField,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordOrder,
    BaseRecordRow,
    BaseRecordUpdate,
)
from ceres._internal.util import MatchMode
from ceres.data import (
    DataObject,
    FromYAML,
    JSONSerializableDict,
    MaybeSequence,
    to_json,
    to_kwargs,
    validate,
)
from ceres.timing import utc

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres._internal.protocols import DatabaseSource, NodeSource
    from ceres.database import DatabaseType


class ParticleRow(BaseRecordRow, kw_only=True):
    __tablename__: ClassVar[str] = "particles"

    type: Mapped[str] = mapped_column(Text)
    data: Mapped[JSONSerializableDict] = mapped_column(JSON)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(
                f"ix_{cls.__tablename__}__type",
                cls.type,
                postgresql_ops={"type": "gin_trgm_ops"},
                postgresql_using="gin",
            ),
        )


ParticleField: TypeAlias = (
    BaseRecordField
    | Literal[
        "type",
        "data",
    ]
)
ParticleOrder: TypeAlias = (
    BaseRecordOrder
    | Literal[
        "type",
        "type:asc",
        "type:desc",
    ]
)

UNKNOWN_TYPE: LiteralString = "__unknown__"


class ParticleData(DataObject, Mapping[str, Any], config=ConfigDict(extra="ignore")):
    __abstract__: ClassVar[bool] = True
    __type__: ClassVar[LiteralString]

    @classmethod
    @override
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        if "__abstract__" not in cls.__dict__:
            cls.__abstract__ = False

        if not cls.__abstract__:
            if "__type__" not in cls.__dict__ or not isinstance(cls.__type__, str):
                raise TypeError(
                    f"{cls} must define `__type__` as a class attribute unless `__abstract__` is set to `True`."
                )

    @override
    def __getitem__(self, key: str, /) -> Any:
        return self.__dict__[key]

    def __setitem__(self, key: str, value: Any, /) -> None:
        self.__dict__[key] = value

    @override
    def __contains__(self, key: object, /) -> bool:
        return key in self.__dict__

    @override
    def __iter__(self) -> Iterator[str]:  # type: ignore
        return iter(self.__dict__.keys())

    @override
    def __len__(self) -> int:
        return len(self.__dict__)

    @override
    def keys(self) -> KeysView[str]:
        return self.__dict__.keys()

    @override
    def values(self) -> ValuesView[Any]:
        return self.__dict__.values()

    @override
    def items(self) -> ItemsView[str, Any]:
        return self.__dict__.items()


DynamicParticleData: TypeAlias = JSONSerializableDict | ParticleData

# ruff: disable[UP046] Need `TypeVar.default` for Python 3.12 compatibility.

if TYPE_CHECKING:
    DataT = TypeVar(
        "DataT",
        bound=DynamicParticleData,
        default=DynamicParticleData,
        covariant=True,
    )
    ConvertedDataT = TypeVar(
        "ConvertedDataT",
        bound=DynamicParticleData,
        default=DynamicParticleData,
        covariant=True,
    )
else:
    DataT = TypeVar(
        "DataT",
        default=DynamicParticleData,
        covariant=True,
    )
    ConvertedDataT = TypeVar(
        "ConvertedDataT",
        default=DynamicParticleData,
        covariant=True,
    )


class ParticleFilterArgs(
    BaseRecordFilterArgs[ParticleField, ParticleOrder],
    Generic[DataT],
    total=False,
):
    cls: ImportString[type[DataT]] | None
    type: MaybeSequence[str] | None
    type_contains: MaybeSequence[str] | None
    type_prefix: MaybeSequence[str] | None
    type_suffix: MaybeSequence[str] | None
    data_contains: MaybeSequence[str] | None
    data_prefix: MaybeSequence[str] | None
    data_suffix: MaybeSequence[str] | None


class ParticleFilter(
    BaseRecordFilter["Particle", ParticleField, ParticleOrder],
    Generic[DataT],
):
    cls: ImportString[builtins.type[DataT]] | None = None
    """Filter by particles being instances of a specific data class."""
    type: MaybeSequence[str] | None = None
    """Filter by `type` being equal to one or more given types."""
    type_contains: MaybeSequence[str] | None = None
    """Filter by `type` containing one or more given substrings."""
    type_prefix: MaybeSequence[str] | None = None
    """Filter by `type` starting with one or more given prefixes."""
    type_suffix: MaybeSequence[str] | None = None
    """Filter by `type` ending with one or more given suffixes."""
    data_contains: MaybeSequence[str] | None = None
    """Filter by whether or not the JSON text of `data` contains one or more given substrings."""
    data_prefix: MaybeSequence[str] | None = None
    """Filter by whether or not the JSON text of `data` starts with one or more given prefixes."""
    data_suffix: MaybeSequence[str] | None = None
    """Filter by whether or not the JSON text of `data` ends with one or more given suffixes."""

    @override
    def _matches(self, obj: Particle[Any], *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super()._matches(obj):
            return False

        if self.cls is not None:
            if not isinstance(obj.data, self.cls):
                return False

        if not util.match_value(obj.type, self.type):
            return False
        if not util.match_string(obj.type, self.type_contains, MatchMode.CONTAINS):
            return False
        if not util.match_string(obj.type, self.type_prefix, MatchMode.PREFIX):
            return False
        if not util.match_string(obj.type, self.type_suffix, MatchMode.SUFFIX):
            return False

        if (
            self.data_contains is not None
            or self.data_prefix is not None
            or self.data_suffix is not None
        ):
            data_json = to_json(obj.data)
            if not util.match_string(data_json, self.data_contains, MatchMode.CONTAINS):
                return False
            if not util.match_string(data_json, self.data_prefix, MatchMode.PREFIX):
                return False
            if not util.match_string(data_json, self.data_suffix, MatchMode.SUFFIX):
                return False

        return True

    @classmethod
    @override
    def _get_row_cls(cls) -> type[ParticleRow]:
        return ParticleRow

    @override
    def _get_where(
        self,
        dialect: DatabaseType,
        *,
        now: datetime | None = None,
    ) -> Iterable[SQLColumnExpression[bool]]:
        now = utc(now)
        yield from super()._get_where(dialect, now=now)
        columns = self._get_row_cls()

        if self.cls is not None:
            if issubclass(self.cls, ParticleData):
                yield columns.type == self.cls.__type__

        if self.type is not None:
            yield util.sql_match_value(columns.type, self.type)
        if self.type_contains is not None:
            yield util.sql_match_string(columns.type, self.type_contains, MatchMode.CONTAINS)
        if self.type_prefix is not None:
            yield util.sql_match_string(columns.type, self.type_prefix, MatchMode.PREFIX)
        if self.type_suffix is not None:
            yield util.sql_match_string(columns.type, self.type_suffix, MatchMode.SUFFIX)

        if self.data_contains is not None:
            yield util.sql_match_string(
                cast(columns.data, Text), self.data_contains, MatchMode.CONTAINS
            )
        if self.data_prefix is not None:
            yield util.sql_match_string(
                cast(columns.data, Text), self.data_prefix, MatchMode.PREFIX
            )
        if self.data_suffix is not None:
            yield util.sql_match_string(
                cast(columns.data, Text), self.data_suffix, MatchMode.SUFFIX
            )


class ParticleCreate(BaseRecordCreate, slots=True):
    type: str
    data: FromYAML[JSONSerializableDict]


class ParticleUpdate(BaseRecordUpdate, total=False):
    type: str
    data: FromYAML[JSONSerializableDict]


class _BaseParticleQuery(
    BaseEntityQuery[
        "Particle[DataT]",
        ParticleFilter[DataT],
        ParticleUpdate,
        "ParticleQuery",
    ],
    Generic[DataT],
):
    __slots__ = ()

    @override
    def _get_query_class(self) -> type[ParticleQuery]:
        return ParticleQuery

    @override
    def _get_transform(self) -> EntityTransform | None:
        data_class = _get_data_class(self._get_resolved_filter(), None)
        if data_class is None:
            return None

        def transform(entity: Particle[DataT]) -> Particle[Any] | None:
            return _convert_or_none(entity, data_class)

        return transform

    @overload
    def where(
        self,
        filter: ParticleFilter[ConvertedDataT] | None = None,
        **kwargs: Unpack[ParticleFilterArgs[ConvertedDataT]],
    ) -> ParticleQuery[ConvertedDataT]: ...

    @overload
    def where(
        self,
        filter: ParticleFilter[Any] | None = None,
        **kwargs: Unpack[ParticleFilterArgs[Any]],
    ) -> ParticleQuery[Any]: ...

    @override
    def where(
        self,
        filter: ParticleFilter[Any] | None = None,
        **kwargs: Unpack[ParticleFilterArgs[Any]],
    ) -> ParticleQuery[Any]:
        return super().where(filter, **kwargs)


class ParticleQuery(  # type: ignore
    _BaseParticleQuery[DataT],
    EntityQuery[
        "Particle[DataT]",
        ParticleFilter[DataT],
        ParticleUpdate,
    ],
    Generic[DataT],
):
    __slots__ = ()


class ParticleManager(
    BaseEntityManager[
        "Particle",
        ParticleRow,
        ParticleCreate,
        ParticleUpdate,
        ParticleFilter,
        ParticleFilterArgs,
    ],
    _BaseParticleQuery[DynamicParticleData],
):
    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Particle)

    @overload
    async def get(self, id: UUID, cls: None = None, /) -> Particle | None: ...

    @overload
    async def get(
        self,
        id: UUID,
        cls: type[DataT],
        /,
    ) -> Particle[DataT] | None: ...

    async def get(
        self,
        id: UUID,
        cls: type[DataT] | None = None,
        /,
    ) -> Particle | None:
        return await self.where(id=id, cls=cls, limit=1).first()


class BoundParticleManager(ParticleManager, BaseNodeManager):
    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)

    @property
    def stream(self) -> ParticleOutputChannel:
        from ceres.event import ParticleEvent

        return ParticleOutputChannel(
            self.__node__.events.stream.every(ParticleEvent)
            .map(lambda event: event.particle)
            .where(lambda particle: self._get_resolved_filter().matches(particle))
        )


class ParticleOutputChannel(
    EntityOutputChannel[
        "Particle",
        ParticleFilter,
        ParticleFilterArgs,
    ],
    Generic[DataT],
):
    __slots__ = ()

    @override
    def _get_filter_class(self) -> type[ParticleFilter]:
        return ParticleFilter

    @overload
    def where(
        self,
        filter: ParticleFilter[DataT] | Callable[[Particle[DataT]], bool] | None = None,
        /,
        **kwargs: Unpack[ParticleFilterArgs[DataT]],
    ) -> ParticleOutputChannel[DataT]: ...

    @overload
    def where(
        self,
        filter: ParticleFilter[ConvertedDataT],
        /,
        **kwargs: Unpack[ParticleFilterArgs[ConvertedDataT]],
    ) -> ParticleOutputChannel[ConvertedDataT]: ...

    @override
    def where(  # type: ignore
        self,
        filter: ParticleFilter | Callable[[Particle], bool] | None = None,
        /,
        **kwargs: Unpack[ParticleFilterArgs],
    ) -> ParticleOutputChannel:
        data_class = _get_data_class(filter, kwargs)
        if data_class is None:
            return super().where(filter, **kwargs)

        return ParticleOutputChannel(
            super()
            .map(lambda particle: particle.convert_or_none(data_class))
            .where(
                filter,
                **kwargs,  # type: ignore
            )
        )


class Particle(BaseRecord, ParticleCreate, Generic[DataT], slots=True):
    if TYPE_CHECKING:
        Manager: ClassVar[type[ParticleManager]] = ParticleManager
        BoundManager: ClassVar[type[BoundParticleManager]] = BoundParticleManager
        Row: ClassVar[type[ParticleRow]] = ParticleRow
        Create: ClassVar[type[ParticleCreate]] = ParticleCreate
        Update: ClassVar[type[ParticleUpdate]] = ParticleUpdate
        Filter: ClassVar[type[ParticleFilter]] = ParticleFilter
        FilterArgs: ClassVar[type[ParticleFilterArgs]] = ParticleFilterArgs
    else:
        Manager: ClassVar[type] = ParticleManager
        BoundManager: ClassVar[type] = BoundParticleManager
        Row: ClassVar[type] = ParticleRow
        Create: ClassVar[type] = ParticleCreate
        Update: ClassVar[type] = ParticleUpdate
        Filter: ClassVar[type] = ParticleFilter
        FilterArgs: ClassVar[type] = ParticleFilterArgs

    Field = ParticleField
    Order = ParticleOrder

    __naming__: ClassVar[EntityNaming] = EntityNaming("particle")

    type: str = UNKNOWN_TYPE
    data: SerializeAsAny[FromYAML[DataT]]

    @model_validator(mode="before")
    @to_kwargs
    @classmethod
    def _validate(cls, values: Any) -> Any:
        if isinstance(values, MutableMapping):
            type = values.get("type", UNKNOWN_TYPE)
            data = values.get("data")
            if type == UNKNOWN_TYPE and isinstance(data, ParticleData):
                try:
                    values["type"] = values["data"].__type__
                except Exception:
                    pass
        elif isinstance(values, Particle):
            type = values.type
            data = values.data
            if type == UNKNOWN_TYPE and isinstance(data, ParticleData):
                try:
                    values.type = type
                except Exception:
                    pass

        return values

    def convert[D: DynamicParticleData](self, cls: builtins.type[D]) -> Particle[D]:
        data = (
            validate(self.data, cls)
            if util.lenient_issubclass(cls, ParticleData)
            else dict(self.data)
        )

        return Particle[cls].__data_object_construct__(
            id=self.id,
            address=self.address,
            timestamp=self.timestamp,
            type=self.type,
            data=data,
        )

    def convert_or_none[D: DynamicParticleData](self, cls: builtins.type[D]) -> Particle[D] | None:
        try:
            return self.convert(cls)
        except ValidationError:
            return None


def _convert_or_none(
    particle: Particle | None,
    data_class: type[DataT] | None,
) -> Particle[DataT] | None:
    if particle is None:
        return None

    if data_class is None:
        return particle  # type: ignore

    try:
        return particle.convert_or_none(data_class)
    except ValueError:
        return None


def _get_data_class(
    filter: ParticleFilter[DataT] | object | None,
    filter_kwargs: ParticleFilterArgs[DataT] | None,
) -> type[DataT] | None:
    data_class = filter_kwargs.get("cls") if filter_kwargs is not None else None
    if data_class is None and isinstance(filter, ParticleFilter):
        data_class = filter.cls

    return data_class


class ParseFailed(Exception):
    """Raised when `ParseableParticleData.parse` fails."""


class ParseableParticleData(ParticleData):
    __abstract__: ClassVar[bool] = True

    @classmethod
    @abstractmethod
    def parse(cls, content: bytes) -> Self: ...


class RegexParticleData(ParseableParticleData):
    __abstract__: ClassVar[bool] = True
    __regex__: ClassVar[bytes | Pattern[bytes]]
    __regex_flags__: ClassVar[int] = re.MULTILINE | re.DOTALL
    __regex_compiled__: ClassVar[Pattern[bytes]]

    @classmethod
    @override
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        regex = getattr(cls, "__regex__", None)
        if not isinstance(regex, bytes):
            raise ValueError(
                f"`{cls}.__regex__` must be defined as `bytes` or `re.Pattern[bytes]`."
            )

        try:
            if isinstance(regex, Pattern):
                cls.__regex_compiled__ = regex
            else:
                cls.__regex_compiled__ = re.compile(cls.__regex__, cls.__regex_flags__)
        except re.error as error:
            raise ValueError(f"Failed to compile `{cls}.__regex__`. {error}")

        missing = sorted(set(cls.__data_object_fields__) - set(cls.__regex_compiled__.groupindex))
        if missing:
            raise ValueError(f"`{cls}.__regex__` is missing named capture groups: {missing}")

        for field in cls.__data_object_fields__:
            if field not in cls.__regex_compiled__.groupindex:
                raise ValueError(
                    f"Field {field!r} is not a named capturing group in `{cls}.__regex__`."
                )

    @classmethod
    @override
    def parse(cls, content: bytes) -> Self:
        match = cls.__regex_compiled__.match(content)
        if match is None:
            raise ParseFailed("Bytes did not match regex pattern.")

        try:
            return validate(match.groupdict(), cls)
        except ValidationError as error:
            raise ParseFailed(f"Bytes matched, but validation failed. {error}") from error
