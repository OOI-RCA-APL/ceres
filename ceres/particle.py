from __future__ import annotations

from collections.abc import Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    ItemsView,
    Iterable,
    KeysView,
    Literal,
    LiteralString,
    MutableMapping,
    Type,
    TypeAlias,
    Unpack,
    ValuesView,
    overload,
    override,
)

from pydantic import ConfigDict, ImportString, SerializeAsAny, ValidationError, model_validator
from sqlalchemy import JSON, Index, Text, cast
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import TypeVar

from ceres._internal import util
from ceres._internal.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    EntityNaming,
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
from ceres.data import FromYAML, ImmutableDataObject, JSONSerializableDict, MaybeSequence, jsonify
from ceres.timing import utc

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres._internal.protocols import DatabaseSource, NodeSource
    from ceres.database import DatabaseType
    from ceres.stream import Stream


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


class ParticleData(ImmutableDataObject, Mapping[str, Any]):
    model_config = ConfigDict(extra="allow")

    __type__: ClassVar[LiteralString]

    @classmethod
    def __init_subclass__(cls) -> None:
        if not hasattr(cls, "__type__") or not isinstance(cls.__type__, str):
            raise ValueError(f"{cls} must define `__type__` as a class attribute")

    @override
    def __getitem__(self, key: str, /) -> Any:
        return self.__dict__[key]

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

    @override
    def __contains__(self, value: Any, /) -> bool:
        return value in self.__dict__


DynamicParticleData: TypeAlias = JSONSerializableDict | ParticleData

if TYPE_CHECKING:
    _T = TypeVar(
        "_T",
        bound=DynamicParticleData,
        default=DynamicParticleData,
        covariant=True,
    )
    _O = TypeVar(
        "_O",
        bound=DynamicParticleData,
        default=DynamicParticleData,
        covariant=True,
    )
else:
    _T = TypeVar(
        "_T",
        default=DynamicParticleData,
        covariant=True,
    )
    _O = TypeVar(
        "_O",
        default=DynamicParticleData,
        covariant=True,
    )


class ParticleFilterArgs(
    BaseRecordFilterArgs[ParticleField, ParticleOrder],
    Generic[_T],
    total=False,
):
    cls: ImportString[Type[_T]] | None
    type: MaybeSequence[str] | None
    type_contains: MaybeSequence[str] | None
    type_prefix: MaybeSequence[str] | None
    type_suffix: MaybeSequence[str] | None
    data_contains: MaybeSequence[str] | None
    data_prefix: MaybeSequence[str] | None
    data_suffix: MaybeSequence[str] | None


class ParticleFilter(
    BaseRecordFilter["Particle", ParticleField, ParticleOrder],
    Generic[_T],
):
    cls: ImportString[Type[_T]] | None = None
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
            data_json = jsonify(obj.data)
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


class ParticleCreate(BaseRecordCreate):
    type: str
    data: FromYAML[JSONSerializableDict]


class ParticleUpdate(BaseRecordUpdate, total=False):
    type: str
    data: FromYAML[JSONSerializableDict]


class _BaseParticleQuery(
    BaseEntityQuery[
        "Particle[_T]",
        ParticleFilter[_T],
        ParticleUpdate,
        "ParticleQuery",
    ],
    Generic[_T],
):
    @override
    def _get_query_class(self) -> type[ParticleQuery]:
        return ParticleQuery

    @override
    def _get_transform(self) -> EntityTransform | None:
        data_class = _get_data_class(self._get_resolved_filter(), None)
        if data_class is None:
            return None

        def transform(entity: Particle[_T]) -> Particle[Any] | None:
            return _convert_or_none(entity, data_class)

        return transform

    @overload
    def where(
        self,
        filter: ParticleFilter[_O] | None = None,
        **kwargs: Unpack[ParticleFilterArgs[_O]],
    ) -> ParticleQuery[_O]: ...

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
        return super().where(filter, **kwargs)  # type: ignore


class ParticleQuery(  # type: ignore
    _BaseParticleQuery[_T],
    EntityQuery[
        "Particle[_T]",
        ParticleFilter[_T],
        ParticleUpdate,
    ],
    Generic[_T],
):
    pass


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
    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Particle)

    @overload
    async def get(self, id: UUID, cls: None = None, /) -> Particle | None: ...

    @overload
    async def get(self, id: UUID, cls: type[_O], /) -> Particle[_O] | None: ...

    async def get(self, id: UUID, cls: type[_O] | None = None, /) -> Particle[_O] | None:
        return await self.where(id=id, cls=cls, limit=1).first()


class BoundParticleManager(ParticleManager, BaseNodeManager):
    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)

    def follow(
        self,
        filter: ParticleFilter[_T] | None = None,
        **kwargs: Unpack[ParticleFilterArgs[_T]],
    ) -> Stream[Particle[_T]]:
        from ceres.event import ParticleEvent

        assert self.__node__ is not None
        resolved = self._get_resolved_filter_args(filter, kwargs)

        if TYPE_CHECKING:
            util.blackhole(ParticleEvent)

        result = (
            self.__node__.events.follow()
            .every(ParticleEvent)
            .map(lambda event: event.particle)
            .filter(resolved.matches)
        )

        return result  # type: ignore


class Particle(BaseRecord, ParticleCreate, Generic[_T]):
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
    data: SerializeAsAny[FromYAML[_T]]

    @model_validator(mode="before")
    @classmethod
    def _validate(cls, value: Any) -> Any:
        if isinstance(value, MutableMapping):
            type = value.get("type", UNKNOWN_TYPE)
            data = value.get("data")
            if type == UNKNOWN_TYPE and isinstance(data, ParticleData):
                try:
                    value["type"] = value["data"].__type__
                except Exception:
                    pass
        elif isinstance(value, Particle):
            type = value.type
            data = value.data
            if type == UNKNOWN_TYPE and isinstance(data, ParticleData):
                try:
                    value.type = type
                except Exception:
                    pass

        return value

    def convert[D: DynamicParticleData](self, cls: Type[D]) -> Particle[D]:
        data = (
            cls.model_validate(self.data)
            if util.lenient_issubclass(cls, ParticleData)
            else dict(self.data)
        )

        return Particle[cls].model_construct(
            id=self.id,
            address=self.address,
            timestamp=self.timestamp,
            type=self.type,
            data=data,
        )

    def convert_or_none[D: DynamicParticleData](self, cls: Type[D]) -> Particle[D] | None:
        try:
            return self.convert(cls)
        except ValidationError:
            return None


def _convert_or_none(
    particle: Particle | None,
    data_class: type[_T] | None,
) -> Particle[_T] | None:
    if particle is None:
        return None

    if data_class is None:
        return particle  # type: ignore

    try:
        return particle.convert_or_none(data_class)
    except ValueError:
        return None


def _get_data_class(
    filter: ParticleFilter[_T] | None,
    filter_kwargs: ParticleFilterArgs[_T] | None,
) -> type[_T] | None:
    data_class = filter_kwargs.get("cls") if filter_kwargs is not None else None
    if data_class is None:
        if filter is not None:
            data_class = filter.cls

    return data_class
