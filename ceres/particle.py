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

from ceres.__internal__.database.types import TextMapper
from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
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
from ceres.__internal__.utilities.typing import extract_annotation
from ceres.__internal__.utilities.undefined import Undefined
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
    from ceres.address import Address
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
    "BinaryRegexParticle",
    "GroupedRegexParticle",
    "ParseFailed",
]


class ParticleRow(BaseRecordRow, kw_only=True):
    """SQLAlchemy row model backing the `particles` table."""

    __tablename__: ClassVar[str] = "particles"

    type: Mapped[str] = mapped_column(TextMapper())
    """Discriminator string identifying the concrete particle data class."""
    data: Mapped[JSONSerializableDict] = mapped_column(JSON)
    """Parsed payload serialized as a JSON object."""

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        # A trigram GIN index lets `type_contains`/`type_prefix`/`type_suffix` filters use
        # an index instead of falling back to a sequential scan.
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
"""Discriminator string used for particles whose concrete type cannot be resolved."""


class ParticleData(DataObject, Mapping[str, Any], config=ConfigDict(extra="ignore")):
    """Base class for the typed payload of a `Particle`.

    Subclasses define the parsed fields extracted from raw bytes. `ParticleData` exposes a
    `Mapping` interface over its attributes, so payload values can be accessed both as
    attributes and as dictionary entries. Unknown fields are silently dropped during
    validation, allowing payloads to evolve without breaking older readers.
    """

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
        """Return a view of the payload's field names."""
        return self.__dict__.keys()

    @override
    def values(self) -> ValuesView[Any]:
        """Return a view of the payload's field values."""
        return self.__dict__.values()

    @override
    def items(self) -> ItemsView[str, Any]:
        """Return a view of the payload's `(field_name, value)` pairs."""
        return self.__dict__.items()


DynamicParticleData: TypeAlias = Annotated[
    SerializeAsAny[JSONSerializableDict | ParticleData],
    Field(union_mode="left_to_right"),
]
"""Type alias accepting either a raw JSON object or a typed `ParticleData` instance.

Used as the default `data` annotation on the base `Particle` class so it can hold either
unstructured JSON (as loaded from the database) or a concrete typed payload.
"""


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
    """`TypedDict` of keyword arguments accepted by `ParticleQuery.where()`."""

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
    """Filter for selecting particles by class, type discriminator, or JSON data content."""

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
            expected = _get_cls_particle_type(self.cls)
            if expected is not None:
                if obj.type != expected:
                    return False
            elif not isinstance(obj.data, self.cls):
                return False

        if not self._match_value(obj.type, self.type):
            return False
        if not self._match_string_contains(obj.type, self.type_contains):
            return False
        if not self._match_string_prefix(obj.type, self.type_prefix):
            return False
        if not self._match_string_suffix(obj.type, self.type_suffix):
            return False

        # Only serialize the payload to JSON if at least one data filter is set, the JSON
        # encode is expensive and most particles do not need it.
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
            expected = _get_cls_particle_type(self.cls)
            if expected is not None:
                yield columns.type == expected
            elif issubclass(self.cls, ParticleData):
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
    """Payload accepted by `ParticleManager.create()` to insert a new particle."""

    type: str
    data: FromYAML[JSONSerializableDict]


class ParticleUpdate(BaseRecordUpdate, total=False):
    """Partial payload accepted by `ParticleManager.update()` to modify an existing particle."""

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
        if cls is None:
            return None

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
    """Query builder returned by `ParticleManager.where()` for selecting particles."""

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
    """Database manager exposing CRUD operations for `Particle` records."""

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
        """Fetch a particle by id, optionally converting its `data` to `cls`.

        Args:
            id: Unique identifier of the particle to fetch.
            cls: Optional `ParticleData` subclass to validate the payload against. When
                provided, the returned particle's `data` is parsed into `cls`.

        Returns:
            The matching particle, or `None` if no particle with the given id exists.
        """
        return await self.where(id=id, cls=cls, limit=1).first()


class BoundParticleManager(ParticleManager, BaseNodeManager):
    """`ParticleManager` bound to a `Node`, exposing live event streams in addition to CRUD."""

    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)

    @property
    def stream(self) -> ParticleOutputChannel:
        """Live `ParticleOutputChannel` of particles emitted by the bound node."""
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
    """Streaming output channel of particles, supporting filtering and class conversion."""

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
        """Return a new channel that only yields particles matching the given filter.

        When a `cls` keyword is present (or carried by the filter), each particle is
        converted to that class before filtering. Particles that fail conversion are
        silently dropped.

        Args:
            filter: A `ParticleFilter`, a callable predicate, or `None`.
            **kwargs: Additional filter keyword arguments forwarded to the underlying
                channel.

        Returns:
            A filtered `ParticleOutputChannel`.
        """
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


class Particle(
    BaseRecord,
    ParticleCreate,
    ConcreteEntity[ParticleRow],
    Generic[DataT],
    slots=True,
):
    """A typed parsed record extracted from raw connection bytes.

    A `Particle` carries the structured payload (`data`) parsed from one or more `Message`
    chunks together with metadata identifying when, where, and from which byte range it was
    extracted. Subclasses bind a concrete `ParticleData` type via the `data` annotation and
    set a stable `type` discriminator string.
    """

    Manager = ParticleManager
    BoundManager = BoundParticleManager
    Create = ParticleCreate
    Update = ParticleUpdate
    Filter = ParticleFilter
    FilterArgs = ParticleFilterArgs
    Field = ParticleField
    Order = ParticleOrder

    __abstract__: ClassVar[bool] = False

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("particle")

    data: DataT
    """Parsed payload, either a typed `ParticleData` subclass or a raw JSON object."""
    span: Annotated[
        tuple[int, int] | None,
        pydantic.Field(exclude_if=lambda value: value is None),
    ] = field(
        default=None,
        compare=False,
        hash=False,
    )
    """Optional `(start, end)` byte offsets locating this particle in its source bytes."""

    @fields_cached_class_property
    @classmethod
    def Data(cls) -> type[DataT]:
        """Resolved `ParticleData` subclass bound to the `data` field of `cls`."""
        return extract_annotation(cls.__data_object_fields__["data"]).type

    @classmethod
    @override
    def __data_object_init_subclass__(cls, **kwargs: Any) -> None:
        super().__data_object_init_subclass__(**kwargs)
        # Skip validation while the base `Particle` class itself is being constructed,
        # the module-level flag flips to `True` once that is complete.
        if not _particle_class_is_defined:
            return

        # A subclass parameterized by an unresolved generic (e.g. `Particle[T]`) is treated
        # as abstract by default since it cannot yet be instantiated with a concrete type.
        if "__abstract__" not in cls.__dict__:
            cls.__abstract__ = cls.__data_object_generic_alias__ is not None

        if not cls.__abstract__:
            if not isinstance(cls.__dict__.get("type"), str):
                raise TypeError(
                    f"`{cls}` must define `type` field with a default `str` value unless "
                    "`__abstract__` is set to `True`."
                )

    def convert[T: Particle[Any]](self, cls: builtins.type[T]) -> T:
        """Return a copy of this particle with `data` validated against `cls.Data`.

        Args:
            cls: Concrete `Particle` subclass to convert to.

        Returns:
            A new `cls` instance carrying the same id, address, timestamp, type, and span
            as `self`, with `data` re-validated against the target payload type.

        Raises:
            ValidationError: If `self.data` cannot be coerced to the target `cls.Data` type.
        """
        data = self.data
        # Typed payloads must be dumped to plain JSON before reconstructing under the
        # target class so Pydantic can re-validate the raw values against `cls.Data`.
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
        """Return a base `Particle` whose `data` is a plain JSON object.

        Useful when serializing or comparing particles without depending on the concrete
        payload class being importable.

        Returns:
            A new dynamic `Particle` carrying the same metadata with `data` reduced to a
            plain JSON-serializable dictionary.
        """
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


def _get_cls_particle_type(cls: type) -> str | None:
    """Return the `type` discriminator a `Particle` subclass declares, or `None`.

    Concrete particle classes declare `type` as a `Literal` field with a default. Classes
    without one (including the base `Particle` and `ParticleData` subclasses) return `None`.
    """
    if not (isinstance(cls, type) and issubclass(cls, Particle)):
        return None

    field = cls.__pydantic_fields__.get("type")
    default = field.default if field is not None else None
    if isinstance(default, str):
        return default

    attribute = getattr(cls, "type", None)
    return attribute if isinstance(attribute, str) else None


def _convert_or_none[ParticleT: Particle[Any]](
    particle: Particle | None,
    cls: type[ParticleT] | None,
) -> ParticleT | None:
    # Pass `None` through unchanged, when no target class is requested return the particle
    # as-is, and drop validation failures so the stream filter simply skips mismatches. Drops
    # are logged because a systematic mismatch (for example a data class that cannot re-validate
    # its own stored payload) silently empties every query result.
    if particle is None:
        return None

    if cls is None:
        return particle  # type: ignore

    try:
        return particle.convert(cls)
    except ValueError as error:
        from ceres.logs import get_logger

        get_logger("ceres.particle").warning(
            f"Dropped particle {particle.id} of type {particle.type!r} while converting to "
            f"{cls.__name__}. {error}"
        )
        return None


def _get_particle_class[T: Particle[Any]](
    filter: ParticleFilter[T] | object | None,
    filter_kwargs: ParticleFilterArgs[T] | None,
) -> type[T] | None:
    # Prefer the explicit `cls` keyword argument over a `cls` field on the filter object.
    cls = filter_kwargs.get("cls") if filter_kwargs is not None else None
    if cls is None:
        if isinstance(filter, ParticleFilter):
            cls = filter.cls

    return cls


class ParseableParticle[DataT: ParticleData = ParticleData](Particle[DataT]):
    """Abstract `Particle` that knows how to parse itself from raw bytes.

    Concrete subclasses (`BinaryParticle`, `RegexParticle`, etc.) implement `from_bytes` to
    decode their payload from a byte sequence.
    """

    __abstract__ = True

    @classmethod
    @abstractmethod
    def from_bytes(
        cls,
        bytes: bytes,
        /,
        address: Address,
        timestamp: DateTime | None = None,
        span: tuple[int, int] | None = None,
    ) -> Self:
        """Parse a particle instance from `bytes`.

        Args:
            bytes: Raw bytes containing a single particle's serialized form.
            address: Address of the node or connection that produced the bytes.
            timestamp: Optional UTC timestamp associated with the source bytes, defaults
                to the current time when not provided.
            span: Optional `(start, end)` byte offsets locating the particle within a
                larger buffer. Defaults to the full extent of `bytes`.

        Returns:
            A new instance of `cls` populated from the parsed payload.

        Raises:
            ParseFailed: If `bytes` cannot be decoded into a valid payload.
        """
        ...

    @classmethod
    def from_message(cls, message: Message, /) -> Self:
        """Parse a particle from a `Message`, propagating its address and timestamp.

        Args:
            message: The source message whose `data` bytes should be parsed.

        Returns:
            A new instance of `cls` parsed from `message.data`.

        Raises:
            ParseFailed: If `message.data` cannot be decoded.
        """
        return cls.from_bytes(
            message.data,
            message.address,
            message.timestamp,
        )


class BinaryParticle[T: ParticleData](ParseableParticle[T]):
    """Particle whose payload is parsed by `unpack`-ing fixed-layout binary fields.

    The payload type (`cls.Data`) describes the binary layout via its field annotations,
    `from_bytes` invokes `unpack` to decode the bytes against that schema.
    """

    __abstract__ = True

    @classmethod
    @override
    def from_bytes(
        cls,
        bytes: bytes,
        /,
        address: Address,
        timestamp: DateTime | None = None,
        span: tuple[int, int] | None = None,
    ) -> Self:
        """Unpack a particle from fixed-layout binary `bytes`.

        Args:
            bytes: Raw bytes containing the binary payload.
            address: Address of the node or connection that produced the bytes.
            timestamp: Optional UTC timestamp, defaults to the current time.
            span: Optional `(start, end)` byte offsets. Defaults to the full extent of
                `bytes`.

        Returns:
            A new instance of `cls` with `data` decoded from the binary layout.

        Raises:
            ParseFailed: If `bytes` cannot be unpacked into a valid payload.
        """
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
    """A regex match located in a `Buffer`, paired with the metadata needed to parse it."""

    parsed: type[T]
    """`RegexParticle` subclass that produced the match and will parse it."""
    address: Address
    """Address of the node or connection that produced the matched bytes."""
    timestamp: DateTime
    """UTC timestamp resolved for the chunk of data containing the match."""
    match: Match[bytes]
    """Underlying `re.Match` describing the matched span and capture groups."""

    @property
    def start(self) -> int:
        """Byte offset of the start of the match within the source buffer."""
        return self.match.start()

    @property
    def end(self) -> int:
        """Byte offset just past the end of the match within the source buffer."""
        return self.match.end()

    @property
    def span(self) -> tuple[int, int]:
        """`(start, end)` byte offsets of the match within the source buffer."""
        return self.match.span()

    @property
    def bytes(self) -> bytes:
        """Raw bytes of the matched region."""
        return self.match.group()

    @property
    def pattern(self) -> Pattern[bytes]:
        """Compiled regex pattern that produced the match."""
        return self.match.re

    @overload
    def parse(self) -> T: ...
    @overload
    def parse[D](self, default: D) -> T | D: ...
    def parse[D](self, default: D = Undefined) -> T | D:
        """Parse the match into a particle, optionally returning a default on failure.

        Args:
            default: Value to return if parsing raises. When omitted, exceptions propagate.

        Returns:
            The parsed particle, or `default` if parsing failed and a default was provided.

        Raises:
            Exception: Any error raised by `from_match` when no `default` is supplied.
        """
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
    """Particle parsed by matching a regex pattern against raw bytes.

    Subclasses set the `regex` class attribute to a compiled byte pattern and implement
    `from_match` to translate a `re.Match` into a particle instance.
    """

    __abstract__ = True

    regex: ClassVar[Pattern[bytes]]
    """Compiled regex pattern used to locate and capture this particle's bytes."""

    @classmethod
    @override
    def from_bytes(
        cls,
        bytes: bytes,
        /,
        address: Address,
        timestamp: DateTime | None = None,
        span: tuple[int, int] | None = None,
    ) -> Self:
        """Match the class regex against `bytes` and parse the result.

        Args:
            bytes: Raw bytes to match the regex against.
            address: Address of the node or connection that produced the bytes.
            timestamp: Optional UTC timestamp, defaults to the current time.
            span: Ignored, the span is derived from the regex match.

        Returns:
            A new instance of `cls` built from the regex match.

        Raises:
            ParseFailed: If `bytes` do not match the regex pattern.
        """
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
        address: Address,
        timestamp: DateTime | None = None,
    ) -> Self:
        """Build a particle instance from a regex `match`.

        Args:
            match: A successful `re.Match` produced by `cls.regex`.
            address: Address of the node or connection that produced the matched bytes.
            timestamp: Optional UTC timestamp for the matched data, defaults to now.

        Returns:
            A new instance of `cls` populated from the captured groups.

        Raises:
            ParseFailed: If the captured groups cannot be validated into a payload.
        """
        ...

    @classmethod
    def scan(
        cls,
        data: Buffer,
        /,
        address: Address,
        timestamp: DateTime | None = None,
    ) -> Iterable[RegexParticleMatch[Self]]:
        """Yield every regex match in `data` paired with its resolved chunk timestamp.

        Args:
            data: Buffer of raw bytes to search.
            address: Address to attach to each yielded match.
            timestamp: Fallback timestamp used when the buffer cannot resolve a chunk timestamp
                for a match's location.

        Yields:
            `RegexParticleMatch` for every non-overlapping match, skipping any match for
            which neither the buffer nor the fallback can supply a timestamp.
        """
        for match in cls.regex.finditer(data):
            # Resolve the timestamp from the buffer chunk containing the last byte of the
            # match, falling back to the original `timestamp` argument so that earlier
            # successful resolutions never leak into later matches.
            match_timestamp = data.timestamp_at(match.end() - 1) or timestamp
            if match_timestamp is None:
                continue

            yield RegexParticleMatch(
                parsed=cls,
                address=address,
                timestamp=match_timestamp,
                match=match,
            )

    @classmethod
    def extract(
        cls,
        data: Buffer,
        /,
        address: Address,
        timestamp: DateTime | None = None,
        errors: Literal["ignore", "raise"] | Callable[[ParseFailed], Any] = "ignore",
    ) -> Iterable[Self]:
        """Scan `data` for matches and yield successfully parsed particles.

        Args:
            data: Buffer of raw bytes to search.
            address: Address to attach to each parsed particle.
            timestamp: Fallback timestamp used when the buffer cannot resolve one.
            errors: How to handle `ParseFailed` exceptions. `"ignore"` skips the failed match,
                `"raise"` re-raises, a callable receives the exception and the loop continues.

        Yields:
            Each successfully parsed particle from `data`.

        Raises:
            ParseFailed: When `errors` is `"raise"` and a match fails to parse.
        """
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
    """`RegexParticle` that maps named regex groups directly onto `ParticleData` fields.

    Each capture group in the pattern is paired with a field of the bound `ParticleData` class,
    either positionally (in declaration order) or by name when the regex uses named groups. The
    captured byte values are validated through the data class to produce the final payload.
    """

    __abstract__ = True

    @classmethod
    @override
    def __data_object_init_subclass__(cls, **kwargs: Any) -> None:
        super().__data_object_init_subclass__(**kwargs)

        # `GroupedRegexParticle` provides a concrete `from_match`, so subclasses are
        # treated as instantiable by default unless they explicitly opt back into abstract.
        if "__abstract__" not in cls.__dict__:
            cls.__abstract__ = False

        if cls.__abstract__ or cls.__data_object_generic_alias__ is not None:
            return

        regex = getattr(cls, "regex", None)
        if not isinstance(regex, Pattern):
            raise ValueError(f"`{cls}.regex` must be defined as `re.Pattern[bytes]` instance.")

        Data = cls.Data
        if not isinstance(Data, type) or not issubclass(Data, ParticleData):
            raise TypeError(f"`{cls}.Data` is unresolved, cannot verify regex groups.")

        # Every field declared on the payload must have a corresponding capture group
        # so validation will not see missing keys at parse time.
        missing = sorted(set(Data.__data_object_fields__) - set(cls.group_indexes))
        if missing:
            raise ValueError(f"`{cls}.regex` is missing capture groups: {missing}")

    @fields_cached_class_property
    @classmethod
    def group_indexes(cls) -> Mapping[str, int]:
        """Mapping from field name to the regex group index that captures it.

        Positional groups are paired with payload fields in declaration order, then any
        explicitly named groups override or extend that mapping by group name.
        """
        return MappingProxyType(
            {
                **dict(zip(cls.__data_object_fields__, range(cls.regex.groups))),
                **cls.regex.groupindex,
            }
        )

    @fields_cached_class_property
    @classmethod
    def group_names(cls) -> Mapping[int, str]:
        """Inverse of `group_indexes`, mapping each regex group index back to its field name."""
        return MappingProxyType({index: name for name, index in cls.group_indexes.items()})

    @classmethod
    @override
    def from_match(
        cls,
        match: Match[bytes],
        address: Address,
        timestamp: DateTime | None = None,
    ) -> Self:
        """Build a particle by mapping named regex groups onto `ParticleData` fields.

        Each named group in `match` is paired with a field on `cls.Data` and
        validated through Pydantic to produce the payload.

        Args:
            match: A successful `re.Match` produced by `cls.regex`.
            address: Address of the node or connection that produced the matched bytes.
            timestamp: Optional UTC timestamp, defaults to the current time.

        Returns:
            A new instance of `cls` with `data` populated from the capture groups.

        Raises:
            ParseFailed: If the captured group values fail validation against `cls.Data`.
        """
        timestamp = utc(timestamp)
        group_values: dict[str, bytes | Any] = match.groupdict()

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
    """Hybrid particle that uses regex to find sync bytes and `unpack` to decode them.

    The regex locates a candidate frame (typically using sync markers and a known length),
    then the matched byte range is handed to `BinaryParticle.from_bytes` for fixed-layout
    decoding via `unpack`.
    """

    __abstract__ = True

    @classmethod
    @override
    def from_match(
        cls,
        match: Match[bytes],
        address: Address,
        timestamp: DateTime | None = None,
    ) -> Self:
        """Decode a particle by unpacking the matched byte range as fixed-layout binary.

        Delegates to `BinaryParticle.from_bytes` with the matched bytes and span.

        Args:
            match: A successful `re.Match` locating the binary frame.
            address: Address of the node or connection that produced the matched bytes.
            timestamp: Optional UTC timestamp, defaults to the current time.

        Returns:
            A new instance of `cls` with `data` decoded from the matched bytes.

        Raises:
            ParseFailed: If the matched bytes cannot be unpacked into a valid payload.
        """
        return cls.from_bytes(
            match.group(),
            address,
            timestamp,
            match.span(),
        )


@dataclass(init=False)
class ParseFailed(Exception):
    """Raised when a `ParseableParticle` fails to decode its payload."""

    message: str
    """Human-readable description of why parsing failed."""
    validation: ValidationError | None
    """Optional underlying Pydantic `ValidationError` when failure was due to validation."""

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
