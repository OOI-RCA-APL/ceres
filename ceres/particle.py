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
from dataclasses import dataclass, field
from re import Match, Pattern
from types import MappingProxyType
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

import pydantic
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
from ceres.__internal__.utilities.classes import fields_cached_class_property
from ceres.__internal__.utilities.typing import get_field_type
from ceres.__internal__.utilities.undefined import Undefined
from ceres.address import Address
from ceres.data import (
    DataObject,
    DateTime,
    FromYAML,
    JSONSerializableDict,
    MaybeSequence,
    construct,
    dump,
    simplify,
    to_json,
    unpack,
    validate,
)
from ceres.timing import utc

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres.__internal__.protocols import DatabaseSource, NodeSource
    from ceres.connection import Buffer
    from ceres.database import DatabaseType
    from ceres.message import Message

__all__ = [
    "Particle",
    "ParticleData",
    "DynamicParticleData",
    "ParseableParticle",
    "RegexParticle",
    "BinaryParticle",
    "BinaryParticleData",
    "BinaryRegexParticle",
    "GroupedRegexParticle",
    "ParseFailed",
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


# ruff: disable[UP046] Need to use `typing.Generic` here due to weird Pydantic issues.
#
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
        cls = self._get_resolved_filter().cls

        def transform(entity: Particle[DataT]) -> Particle[Any] | None:
            return _convert_or_none(entity, cls)

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
        cls = _get_particle_class(filter, kwargs)
        if cls is None:
            return super().where(filter, **kwargs)

        return ParticleOutputChannel(
            super()
            .map(lambda particle: _convert_or_none(particle, cls))
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
    span: Annotated[
        tuple[int, int] | None,
        pydantic.Field(exclude_if=lambda value: value is None),
    ] = field(
        default=None,
        compare=False,
        hash=False,
    )

    @fields_cached_class_property
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

    def convert[T: Particle[Any]](self, cls: builtins.type[T]) -> T:
        data = self.data
        if not isinstance(data, dict):
            data = dump(data)

        return cls(
            id=self.id,
            address=self.address,
            timestamp=self.timestamp,
            type=self.type,
            data=data,
            span=self.span,
        )

    def to_dynamic(self) -> Particle:
        return construct(
            Particle,
            id=self.id,
            address=self.address,
            timestamp=self.timestamp,
            type=self.type,
            data=simplify(self.data),
            span=self.span,
        )


_particle_class_is_defined = True


def _convert_or_none[ParticleT: Particle[Any]](
    particle: Particle | None,
    cls: type[ParticleT] | None,
) -> ParticleT | None:
    if particle is None:
        return None

    if cls is None:
        return particle  # type: ignore

    try:
        return particle.convert(cls)
    except ValueError:
        return None


def _get_particle_class[T: Particle[Any]](
    filter: ParticleFilter[T] | object | None,
    filter_kwargs: ParticleFilterArgs[T] | None,
) -> type[T] | None:
    cls = filter_kwargs.get("cls") if filter_kwargs is not None else None
    if cls is None:
        if isinstance(filter, ParticleFilter):
            cls = filter.cls

    return None


class ParseableParticle[DataT: ParticleData = ParticleData](Particle[DataT]):
    __abstract__ = True

    @classmethod
    @abstractmethod
    def from_bytes(
        cls,
        bytes: bytes,
        /,
        address: Address = Address.ROOT,
        timestamp: DateTime | None = None,
        span: tuple[int, int] | None = None,
    ) -> Self: ...

    @classmethod
    def from_message(cls, message: Message, /) -> Self:
        return cls.from_bytes(
            message.data,
            message.address,
            message.timestamp,
        )


class BinaryParticle[T: ParticleData](ParseableParticle[T]):
    __abstract__ = True

    @classmethod
    @override
    def from_bytes(
        cls,
        bytes: bytes,
        /,
        address: Address = Address.ROOT,
        timestamp: DateTime | None = None,
        span: tuple[int, int] | None = None,
    ) -> Self:
        timestamp = utc(timestamp)
        if span is None:
            span = (0, len(bytes))

        data = unpack(cls.Data, bytes)

        return construct(
            cls,
            type=cls.type,
            address=address,
            timestamp=timestamp,
            data=data,
            span=span,
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class RegexParticleMatch[T: RegexParticle[Any]]:
    parsed: type[T]
    address: Address
    timestamp: DateTime
    match: Match[bytes]

    @property
    def start(self) -> int:
        return self.match.start()

    @property
    def end(self) -> int:
        return self.match.end()

    @property
    def span(self) -> tuple[int, int]:
        return self.match.span()

    @property
    def bytes(self) -> bytes:
        return self.match.group()

    @property
    def pattern(self) -> Pattern[bytes]:
        return self.match.re

    @overload
    def parse(self) -> T: ...
    @overload
    def parse[D](self, default: D) -> T | D: ...
    def parse[D](self, default: D = Undefined) -> T | D:
        try:
            return self.parsed.from_match(
                self.match,
                self.address,
                self.timestamp,
            )
        except Exception:
            if default is not Undefined:
                return default

            raise


class RegexParticle[T: ParticleData](ParseableParticle[T]):
    __abstract__ = True

    regex: ClassVar[Pattern[bytes]]

    @classmethod
    @override
    def from_bytes(
        cls,
        bytes: bytes,
        /,
        address: Address = Address.ROOT,
        timestamp: DateTime | None = None,
        span: tuple[int, int] | None = None,
    ) -> Self:
        match = cls.regex.match(bytes)
        if match is None:
            raise ParseFailed("Bytes did not match regex pattern.")

        return cls.from_match(match, address, timestamp)

    @classmethod
    @abstractmethod
    def from_match(
        cls,
        match: Match[bytes],
        /,
        address: Address = Address.ROOT,
        timestamp: DateTime | None = None,
    ) -> Self: ...

    @classmethod
    def scan(
        cls,
        data: Buffer,
        /,
        address: Address = Address.ROOT,
        timestamp: DateTime | None = None,
    ) -> Iterable[RegexParticleMatch[Self]]:
        for match in cls.regex.finditer(data):
            timestamp = data.timestamp_at(match.end() - 1) or timestamp
            if timestamp is None:
                continue

            yield RegexParticleMatch(
                parsed=cls,
                address=address,
                timestamp=timestamp,
                match=match,
            )

    @classmethod
    def extract(
        cls,
        data: Buffer,
        /,
        address: Address = Address.ROOT,
        timestamp: DateTime | None = None,
        errors: Literal["ignore", "raise"] | Callable[[ParseFailed], Any] = "ignore",
    ) -> Iterable[Self]:
        for match in cls.scan(data, address, timestamp):
            try:
                yield match.parse()
            except ParseFailed as exception:
                if errors == "ignore":
                    continue
                if errors == "raise":
                    raise

                errors(exception)


class GroupedRegexParticle[T: ParticleData](RegexParticle[T]):
    __abstract__ = True

    @classmethod
    @override
    def __data_object_init_subclass__(cls, **kwargs: Any) -> None:
        super().__data_object_init_subclass__(**kwargs)

        if "__abstract__" not in cls.__dict__:
            cls.__abstract__ = False

        if cls.__abstract__ or cls.__data_object_is_generic_alias__:
            return

        regex = getattr(cls, "regex", None)
        if not isinstance(regex, Pattern):
            raise ValueError(f"`{cls}.regex` must be defined as `re.Pattern[bytes]` instance.")

        Data = cls.Data
        if not isinstance(Data, type) or not issubclass(Data, ParticleData):
            raise TypeError(f"`{cls}.Data` is unresolved, cannot verify regex groups.")

        missing = sorted(set(Data.__data_object_fields__) - set(cls.group_indexes))
        if missing:
            raise ValueError(f"`{cls}.regex` is missing capture groups: {missing}")

    @fields_cached_class_property
    @classmethod
    def group_indexes(cls) -> Mapping[str, int]:
        return MappingProxyType(
            {
                **dict(zip(cls.__data_object_fields__, range(cls.regex.groups))),
                **cls.regex.groupindex,
            }
        )

    @fields_cached_class_property
    @classmethod
    def group_names(cls) -> Mapping[int, str]:
        return MappingProxyType({index: name for name, index in cls.group_indexes.items()})

    @classmethod
    @override
    def from_match(
        cls,
        match: Match[bytes],
        address: Address = Address.ROOT,
        timestamp: DateTime | None = None,
    ) -> Self:
        timestamp = utc(timestamp)
        group_names = cls.group_names
        group_values: dict[str, bytes] = {
            group_names[i]: value for i, value in enumerate(match.groups())
        }

        try:
            data: T = validate(cls.Data, group_values)
        except ValidationError as error:
            raise ParseFailed("Regex group(s) validation failed.", error) from error

        return construct(
            cls,
            type=cls.type,
            address=address,
            timestamp=timestamp,
            data=data,
            span=match.span(),
        )


class BinaryRegexParticle[T: ParticleData](BinaryParticle[T], RegexParticle[T]):
    __abstract__ = True

    @classmethod
    @override
    def from_match(
        cls,
        match: Match[bytes],
        address: Address = Address.ROOT,
        timestamp: DateTime | None = None,
    ) -> Self:
        return cls.from_bytes(
            match.group(),
            address,
            timestamp,
            match.span(),
        )


@dataclass(init=False)
class ParseFailed(Exception):
    message: str
    validation: ValidationError | None

    def __init__(
        self,
        message: object,
        validation: ValidationError | None = None,
    ) -> None:
        super().__init__(message)
        self.message = str(message)
        self.validation = validation

    @override
    def __str__(self) -> str:
        if self.validation is None:
            return self.message

        return f"{self.message} {self.validation}"
