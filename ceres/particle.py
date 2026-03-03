import builtins
import re
import typing
from abc import abstractmethod
from collections.abc import (
    Callable,
    ItemsView,
    Iterable,
    Iterator,
    KeysView,
    Mapping,
    ValuesView,
)
from re import Pattern
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Generic,
    Literal,
    LiteralString,
    Self,
    TypeAlias,
    TypeVar,
    Unpack,
    overload,
    override,
)

from pydantic import ConfigDict, Field, ImportString, SerializeAsAny, ValidationError
from sqlalchemy import JSON, Index, Text, cast
from sqlalchemy.orm import Mapped, mapped_column

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
from ceres._internal.util import MatchMode, class_property
from ceres.data import (
    DataObject,
    FromYAML,
    JSONSerializableDict,
    MaybeSequence,
    construct,
    simplify,
    to_json,
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
    from ceres.message import Message

__all__ = [
    "Particle",
    "ParticleData",
    "DynamicParticleData",
    "ParseableParticle",
    "RegexParticle",
]


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


type ParticleField = (
    BaseRecordField
    | Literal[
        "type",
        "data",
    ]
)
type ParticleOrder = (
    BaseRecordOrder
    | Literal[
        "type",
        "type:asc",
        "type:desc",
    ]
)

UNKNOWN_TYPE: LiteralString = "__unknown__"


class ParticleData(DataObject, Mapping[str, Any], config=ConfigDict(extra="ignore")):
    __slots__ = ("__dict__",)

    @override
    def __getitem__(self, key: str, /) -> Any:
        return self.__dict__[key]

    def __setitem__(self, key: str, value: Any, /) -> None:
        self.__dict__[key] = value  # type: ignore

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


DynamicParticleData: TypeAlias = Annotated[
    SerializeAsAny[JSONSerializableDict | ParticleData],
    Field(union_mode="left_to_right"),
]


# ruff: disable[UP046] Need `TypeVar.default` for Python 3.12 compatibility.

if TYPE_CHECKING:
    ParticleT = TypeVar(
        "ParticleT",
        bound="Particle",
        default="Particle",
        covariant=True,
    )
    ConvertedParticleT = TypeVar(
        "ConvertedParticleT",
        bound="Particle",
        default="Particle",
        covariant=True,
    )
    DataT = TypeVar(
        "DataT",
        bound=DynamicParticleData,
        default=DynamicParticleData,
        covariant=True,
    )
    ConvertedDataT = TypeVar(
        "ConvertedDataT",
        bound=ParticleData,
        default=ParticleData,
        covariant=True,
    )
else:
    ParticleT = TypeVar(
        "ParticleT",
        default="Particle",
        covariant=True,
    )
    DataT = TypeVar(
        "DataT",
        default=DynamicParticleData,
        covariant=True,
    )
    ConvertedDataT = TypeVar(
        "ConvertedDataT",
        bound=ParticleData,
        default=ParticleData,
        covariant=True,
    )


class ParticleFilterArgs(
    BaseRecordFilterArgs[ParticleField, ParticleOrder],
    Generic[ParticleT],
    total=False,
):
    cls: ImportString[type[ParticleT]] | None
    type: MaybeSequence[str] | None
    type_contains: MaybeSequence[str] | None
    type_prefix: MaybeSequence[str] | None
    type_suffix: MaybeSequence[str] | None
    data_contains: MaybeSequence[str] | None
    data_prefix: MaybeSequence[str] | None
    data_suffix: MaybeSequence[str] | None


class ParticleFilter(
    BaseRecordFilter["Particle", ParticleField, ParticleOrder],
    Generic[ParticleT],
):
    cls: ImportString[builtins.type[ParticleT]] | None = Field(default=None, alias="class")
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
                yield columns.type == self.cls.type

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
        "ParticleT",
        ParticleFilter[ParticleT],
        ParticleUpdate,
        "ParticleQuery",
    ],
    Generic[ParticleT],
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
        filter: ParticleFilter[ConvertedParticleT] | None = None,
        **kwargs: Unpack[ParticleFilterArgs[ConvertedParticleT]],
    ) -> ParticleQuery[ConvertedParticleT]: ...

    @overload
    def where(
        self,
        filter: ParticleFilter[Any] | None = None,
        **kwargs: Unpack[ParticleFilterArgs[Any]],
    ) -> ParticleQuery[Any]: ...

    @override
    def where(  # type: ignore
        self,
        filter: ParticleFilter[Any] | None = None,
        **kwargs: Unpack[ParticleFilterArgs[Any]],
    ) -> ParticleQuery[Any]:
        return super().where(filter, **kwargs)


class ParticleQuery(  # type: ignore
    _BaseParticleQuery[ParticleT],
    EntityQuery[
        "ParticleT",
        ParticleFilter[ParticleT],
        ParticleUpdate,
    ],
    Generic[ParticleT],
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
    _BaseParticleQuery["Particle"],
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
        "ParticleT",
        ParticleFilter,
        ParticleFilterArgs,
    ],
    Generic[ParticleT],
):
    __slots__ = ()

    @override
    def _get_filter_class(self) -> type[ParticleFilter]:
        return ParticleFilter

    @overload
    def where(
        self,
        **kwargs: Unpack[ParticleFilterArgs[ConvertedParticleT]],
    ) -> ParticleOutputChannel[ConvertedParticleT]: ...

    @overload
    def where(
        self,
        filter: ParticleFilter[ConvertedParticleT] | None = None,
        /,
        **kwargs: Unpack[ParticleFilterArgs[ConvertedParticleT]],
    ) -> ParticleOutputChannel[ConvertedParticleT]: ...

    @overload
    def where(
        self,
        filter: ParticleFilter[ParticleT] | Callable[[ParticleT], bool] | None = None,
        /,
        **kwargs: Unpack[ParticleFilterArgs[ParticleT]],
    ) -> ParticleOutputChannel[ParticleT]: ...

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
            .map(lambda particle: _convert_or_none(particle, data_class))
            .where(
                filter,
                **kwargs,  # type: ignore
            )
        )


_particle_class_is_defined = False
_particle_generic_alias_class_cache: dict[
    tuple[type[Particle], type[ParticleData]], type[Particle[Any]]
] = {}


class Particle(BaseRecord, ParticleCreate, Generic[DataT], slots=True):
    Manager = ParticleManager
    BoundManager = BoundParticleManager
    Row = ParticleRow
    Create = ParticleCreate
    Update = ParticleUpdate
    Filter = ParticleFilter
    FilterArgs = ParticleFilterArgs
    Field = ParticleField
    Order = ParticleOrder

    __abstract__: ClassVar[bool] = False

    if TYPE_CHECKING:
        __data_class__: ClassVar[type[ParticleData] | None] = None
    else:
        __data_class__: ClassVar[Any] = None

    __naming__: ClassVar[EntityNaming] = EntityNaming("particle")

    @class_property
    @classmethod
    def Data(cls) -> type[DataT]:
        Data: type[Any] = cls.__data_class__ or ParticleData
        return Data

    @classmethod
    @override
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        if _particle_class_is_defined:
            if "__abstract__" not in cls.__dict__:
                cls.__abstract__ = False

            if not cls.__abstract__:
                if not isinstance(cls.__dict__.get("type"), str):
                    raise TypeError(
                        f"`{cls}` must define `type` field with a default `str` value unless "
                        "`__abstract__` is set to `True`."
                    )

    def __class_getitem__(cls, args: Any | tuple[Any]) -> type[Self]:
        alias = typing.cast(
            "type[Self]",
            super().__class_getitem__(args),  # type: ignore
        )

        if not isinstance(args, tuple):
            args = (args,)

        data_class: object = args[0] if args else None
        if isinstance(data_class, TypeVar):
            return alias

        if not isinstance(data_class, type) or not issubclass(data_class, ParticleData):
            raise ValueError(
                f"First generic argument of `{cls}` must be a subclass of `ParticleData`. "
                f"Got {repr(data_class) if args else None}."
            )

        cached = _particle_generic_alias_class_cache.get((cls, data_class))
        if cached is not None:
            return typing.cast("type[Self]", cached)

        class GenericAlias(alias):
            __abstract__ = True
            __data_class__ = data_class

        GenericAlias: type[Any] = GenericAlias
        GenericAlias.__name__ = f"{cls.__qualname__}[{data_class.__name__}]"
        GenericAlias.__qualname__ = cls.__qualname__
        GenericAlias = _particle_generic_alias_class_cache.setdefault(
            (cls, data_class), GenericAlias
        )

        return typing.cast("type[Self]", GenericAlias)

    type: str
    data: FromYAML[DataT]

    def convert[ConvertedDataT: DynamicParticleData](
        self,
        cls: builtins.type[ConvertedDataT],
    ) -> Particle[ConvertedDataT]:
        data = (
            validate(cls, self.data)
            if util.lenient_issubclass(cls, ParticleData)
            else dict(self.data)
        )

        return construct(
            Particle[cls] if TYPE_CHECKING else Particle,
            id=self.id,
            address=self.address,
            timestamp=self.timestamp,
            type=self.type,
            data=data,
        )

    def to_dynamic(self) -> Particle:
        return construct(
            Particle,
            id=self.id,
            address=self.address,
            timestamp=self.timestamp,
            type=self.type,
            data=simplify(self.data),
        )


_particle_class_is_defined = True


def _convert_or_none[DataT: DynamicParticleData = DynamicParticleData](
    particle: Particle | None,
    data_class: type[DataT] | None,
) -> Particle[DataT] | None:
    if particle is None:
        return None

    if data_class is None:
        return particle  # type: ignore

    try:
        return particle.convert(data_class)
    except ValueError:
        return None


def _get_data_class(
    filter: ParticleFilter[Particle[DataT]] | object | None,
    filter_kwargs: ParticleFilterArgs[Particle[DataT]] | None,
) -> type[DataT] | None:
    particle_class = filter_kwargs.get("cls") if filter_kwargs is not None else None
    if particle_class is None and isinstance(filter, ParticleFilter) and filter.cls is not None:
        return filter.cls.Data  # type: ignore

    return None


class ParseFailed(Exception):
    """Raised when `ParseableParticle.parse` fails."""


class ParseableParticle[DataT: ParticleData = ParticleData](Particle[DataT]):
    __abstract__: ClassVar[bool] = True

    @classmethod
    @abstractmethod
    def parse(cls, message: Message, /) -> Self: ...


class RegexParticle[DataT: ParticleData](ParseableParticle[DataT]):
    __abstract__: ClassVar[bool] = True
    __regex__: ClassVar[bytes | Pattern[bytes]]
    __regex_flags__: ClassVar[int] = re.DOTALL
    __regex_compiled__: ClassVar[Pattern[bytes]]

    @classmethod
    @override
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        if "__abstract__" not in cls.__dict__:
            cls.__abstract__ = False

        if cls.__abstract__:
            return

        regex = getattr(cls, "__regex__", None)
        if not isinstance(regex, bytes):
            raise ValueError(
                f"`{cls}.__regex__` must be defined as `bytes` or `re.Pattern[bytes]`."
            )

        Data = cls.__data_class__
        if Data is None:
            raise TypeError(f"`{cls}.__data_class__` is unset, cannot verify regex groups.")

        try:
            if isinstance(regex, Pattern):
                cls.__regex_compiled__ = regex
            else:
                cls.__regex_compiled__ = re.compile(cls.__regex__, cls.__regex_flags__)
        except re.error as error:
            raise ValueError(f"Failed to compile `{cls}.__regex__`. {error}")

        missing = sorted(set(Data.__data_object_fields__) - set(cls.__regex_compiled__.groupindex))
        if missing:
            raise ValueError(f"`{cls}.__regex__` is missing named capture groups: {missing}")

        for field in Data.__data_object_fields__:
            if field not in cls.__regex_compiled__.groupindex:
                raise ValueError(
                    f"Field {field!r} is not a named capturing group in `{cls}.__regex__`."
                )

    @classmethod
    @override
    def parse(cls, message: Message, /) -> Self:
        match = cls.__regex_compiled__.match(message.data)
        if match is None:
            raise ParseFailed("Message data did not match regex pattern.")

        try:
            data = validate(cls.Data, match.groupdict())
        except ValidationError as error:
            raise ParseFailed(f"Message data matched, but validation failed. {error}") from error

        return construct(
            cls,
            type=cls.type,
            timestamp=message.timestamp,
            address=message.address,
            data=data,
        )
