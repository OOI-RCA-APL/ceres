import builtins
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

from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    EntityNaming,
    EntityOutputChannel,
    EntityQuery,
    EntityTransform,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.__internal__.record import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordField,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordOrder,
    BaseRecordRow,
    BaseRecordUpdate,
)
from ceres.__internal__.utilities.classes import cached_class_property
from ceres.__internal__.utilities.typing import get_field_type, lenient_issubclass
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

    from ceres.__internal__.protocols import DatabaseSource, NodeSource
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

        if not self._match_value(obj.type, self.type):
            return False
        if not self._match_string_contains(obj.type, self.type_contains):
            return False
        if not self._match_string_prefix(obj.type, self.type_prefix):
            return False
        if not self._match_string_suffix(obj.type, self.type_suffix):
            return False

        if (
            self.data_contains is not None
            or self.data_prefix is not None
            or self.data_suffix is not None
        ):
            data_json = to_json(obj.data)
            if not self._match_string_contains(data_json, self.data_contains):
                return False
            if not self._match_string_prefix(data_json, self.data_prefix):
                return False
            if not self._match_string_suffix(data_json, self.data_suffix):
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
            yield self._sql_match_value(columns.type, self.type)
        if self.type_contains is not None:
            yield self._sql_match_string_contains(columns.type, self.type_contains)
        if self.type_prefix is not None:
            yield self._sql_match_string_prefix(columns.type, self.type_prefix)
        if self.type_suffix is not None:
            yield self._sql_match_string_suffix(columns.type, self.type_suffix)

        if self.data_contains is not None:
            yield self._sql_match_string_contains(cast(columns.data, Text), self.data_contains)
        if self.data_prefix is not None:
            yield self._sql_match_string_prefix(cast(columns.data, Text), self.data_prefix)
        if self.data_suffix is not None:
            yield self._sql_match_string_suffix(cast(columns.data, Text), self.data_suffix)


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

    __naming__: ClassVar[EntityNaming] = EntityNaming("particle")

    data: DataT

    @cached_class_property
    @classmethod
    def Data(cls) -> type[DataT]:
        return get_field_type(cls.__data_object_fields__["data"])

    @classmethod
    @override
    def __data_object_init_subclass__(cls, **kwargs: Any) -> None:
        super().__data_object_init_subclass__(**kwargs)
        if not _particle_class_is_defined:
            return

        if "__abstract__" not in cls.__dict__:
            cls.__abstract__ = cls.__data_object_is_generic_alias__

        if not cls.__abstract__:
            if not isinstance(cls.__dict__.get("type"), str):
                raise TypeError(
                    f"`{cls}` must define `type` field with a default `str` value unless "
                    "`__abstract__` is set to `True`."
                )

    def convert[ConvertedDataT: DynamicParticleData](
        self,
        cls: builtins.type[ConvertedDataT],
    ) -> Particle[ConvertedDataT]:
        data = (
            validate(cls, self.data) if lenient_issubclass(cls, ParticleData) else dict(self.data)
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
    regex_check_groups: ClassVar[bool] = True
    regex: ClassVar[Pattern[bytes]]

    @classmethod
    @override
    def __data_object_init_subclass__(cls, **kwargs: Any) -> None:
        super().__data_object_init_subclass__(**kwargs)

        if "__abstract__" not in cls.__dict__:
            cls.__abstract__ = False

        if cls.__abstract__ or cls.__data_object_is_generic_alias__:
            return

        regex = getattr(cls, "regex", None)
        if not isinstance(regex, Pattern) or not isinstance(regex.pattern, bytes):
            raise ValueError(f"`{cls}.regex` must be defined as `re.Pattern[bytes]` instance.")

        if cls.regex_check_groups:
            Data = cls.Data
            if not isinstance(Data, type) or not issubclass(Data, ParticleData):
                raise TypeError(f"`{cls}.Data` is unresolved, cannot verify regex groups.")

            missing = sorted(set(Data.__data_object_fields__) - set(cls.regex.groupindex))
            if missing:
                raise ValueError(f"`{cls}.regex` is missing named capture groups: {missing}")

            for field in Data.__data_object_fields__:
                if field not in cls.regex.groupindex:
                    raise ValueError(
                        f"Field {field!r} is not a named capturing group in `{cls}.regex`."
                    )

    @classmethod
    @override
    def parse(cls, message: Message, /) -> Self:
        match = cls.regex.match(message.data)
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
