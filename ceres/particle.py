from __future__ import annotations

from abc import ABC
from collections.abc import Mapping
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Generic,
    ItemsView,
    Iterable,
    KeysView,
    Literal,
    LiteralString,
    MutableMapping,
    Sequence,
    Type,
    TypeAlias,
    ValuesView,
    override,
)

from pydantic import ConfigDict, Field, SerializeAsAny, ValidationError, model_validator
from pydantic.types import ImportString
from sqlalchemy import cast
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import JSON, Text
from typing_extensions import TypeVar

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.entity import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordField,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordOrder,
    BaseRecordRow,
    BaseRecordUpdate,
)
from ceres._internal.lazy import lazy_imports
from ceres.data import FromYAML, ImmutableDataObject, JSONDict, jsonify
from ceres.timing import utc

with lazy_imports(__name__):
    from sqlalchemy.schema import Index, SchemaItem
    from sqlalchemy.sql import SQLColumnExpression, or_

    from ceres._internal import util
    from ceres.database.enums import DatabaseType


class ParticleRow(BaseRecordRow, kw_only=True):
    __tablename__: ClassVar[str] = "particles"

    type: Mapped[str] = mapped_column(Text)
    data: Mapped[JSONDict] = mapped_column(JSON)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(
                f"ix__{cls.__tablename__}__type",
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
        "-type",
    ]
)

UNKNOWN_TYPE: LiteralString = "__unknown__"


class ParticleData(ImmutableDataObject, Mapping[str, Any], ABC):
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


DynamicParticleData: TypeAlias = ParticleData | JSONDict

if TYPE_CHECKING:
    _T = TypeVar(
        "_T",
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


class ParticleFilterArgs(
    BaseRecordFilterArgs[ParticleField, ParticleOrder],
    Generic[_T],
    total=False,
):
    cls: ImportString[Type[_T]] | None
    type: str | Sequence[str] | None
    type_contains: str | Sequence[str] | None
    type_prefix: str | Sequence[str] | None
    type_suffix: str | Sequence[str] | None
    data_contains: str | Sequence[str] | None
    data_prefix: str | Sequence[str] | None
    data_suffix: str | Sequence[str] | None


class ParticleFilter(
    BaseRecordFilter["Particle", ParticleField, ParticleOrder],
    Generic[_T],
):
    cls: Annotated[ImportString[Type[_T]] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter by particle data class.",
    )
    type: Annotated[str | Sequence[str] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter by particle type(s).",
    )
    type_contains: Annotated[str | Sequence[str] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter by particle type(s) containing a given substring.",
    )
    type_prefix: Annotated[str | Sequence[str] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter by particle type(s) with a common prefix.",
    )
    type_suffix: Annotated[str | Sequence[str] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter by particle type(s) with a common suffix.",
    )
    data_contains: Annotated[str | Sequence[str] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter particle data containing a given substring.",
    )
    data_prefix: Annotated[str | Sequence[str] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter particle data with a common prefix.",
    )
    data_suffix: Annotated[str | Sequence[str] | None, CLIOption(str)] = Field(
        default=None,
        description="Filter particle data with a common suffix.",
    )

    @override
    def matches(self, obj: Particle[Any], *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super().matches(obj):
            return False

        if self.cls is not None:
            if not isinstance(obj.data, self.cls):
                return False

        if self.type is not None:
            if obj.type not in util.as_sequence(self.type):
                return False
        if self.type_contains is not None:
            if not any(obj.type in substring for substring in util.as_sequence(self.type_contains)):
                return False
        if self.type_prefix is not None:
            if not any(
                obj.type.startswith(prefix) for prefix in util.as_sequence(self.type_prefix)
            ):
                return False
        if self.type_suffix is not None:
            if not any(
                obj.type.startswith(suffix) for suffix in util.as_sequence(self.type_suffix)
            ):
                return False

        if (
            self.data_contains is not None
            or self.data_prefix is not None
            or self.data_suffix is not None
        ):
            data_json = jsonify(obj.data)
            if self.data_contains is not None:
                if not any(
                    substring in data_json for substring in util.as_sequence(self.data_contains)
                ):
                    return False
            if self.data_prefix is not None:
                if not any(
                    data_json.startswith(prefix) for prefix in util.as_sequence(self.data_prefix)
                ):
                    return False
            if self.data_suffix is not None:
                if not any(
                    data_json.startswith(suffix) for suffix in util.as_sequence(self.data_suffix)
                ):
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
            yield columns.type.in_(util.as_sequence(self.type))
        if self.type_contains is not None:
            yield or_(
                False,
                *(columns.type.contains(type) for type in util.as_sequence(self.type_contains)),
            )
        if self.type_prefix is not None:
            yield or_(
                False,
                *(columns.type.startswith(prefix) for prefix in util.as_sequence(self.type_prefix)),
            )
        if self.type_suffix is not None:
            yield or_(
                False,
                *(columns.type.endswith(suffix) for suffix in util.as_sequence(self.type_suffix)),
            )

        if self.data_contains is not None:
            yield or_(
                False,
                *(
                    cast(columns.data, Text).contains(substring)
                    for substring in util.as_sequence(self.data_contains)
                ),
            )
        if self.data_prefix is not None:
            yield or_(
                False,
                *(
                    cast(columns.data, Text).startswith(prefix)
                    for prefix in util.as_sequence(self.data_prefix)
                ),
            )
        if self.data_suffix is not None:
            yield or_(
                False,
                *(
                    cast(columns.data, Text).endswith(suffix)
                    for suffix in util.as_sequence(self.data_suffix)
                ),
            )


class ParticleCreate(BaseRecordCreate):
    type: Annotated[str, CLIOption(str)]
    data: Annotated[FromYAML[JSONDict], CLIOption(str, metavar="JSON/YAML OBJECT")]


class ParticleUpdate(BaseRecordUpdate, total=False):
    type: str
    data: FromYAML[JSONDict]


class Particle(BaseRecord, ParticleCreate, Generic[_T]):
    if TYPE_CHECKING:
        Row: ClassVar[type[ParticleRow]] = ParticleRow
        Create: ClassVar[type[ParticleCreate]] = ParticleCreate
        Update: ClassVar[type[ParticleUpdate]] = ParticleUpdate
        Filter: ClassVar[type[ParticleFilter]] = ParticleFilter
        FilterArgs: ClassVar[type[ParticleFilterArgs]] = ParticleFilterArgs
    else:
        Row: ClassVar[type] = ParticleRow
        Create: ClassVar[type] = ParticleCreate
        Update: ClassVar[type] = ParticleUpdate
        Filter: ClassVar[type] = ParticleFilter
        FilterArgs: ClassVar[type] = ParticleFilterArgs

    Field = ParticleField
    Order = ParticleOrder

    type: str = UNKNOWN_TYPE
    data: SerializeAsAny[_T]

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
