from __future__ import annotations

from abc import ABC, abstractmethod
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    AsyncIterable,
    ClassVar,
    Generic,
    Iterable,
    Literal,
    LiteralString,
    Mapping,
    MutableMapping,
    Sequence,
    override,
)

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import JSON, String, Text
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
from ceres.data import ImmutableDataObject, JSONDict, jsonify
from ceres.error import ParticleError
from ceres.message import Message
from ceres.result import Result

with lazy_imports(__name__):
    from sqlalchemy.sql import SQLColumnExpression, cast, or_

    from ceres._internal import util
    from ceres.database.enums import DatabaseType


class ParticleRow(BaseRecordRow, kw_only=True):
    __tablename__: ClassVar[str] = "particles"

    type: Mapped[str] = mapped_column(String)
    data: Mapped[JSONDict] = mapped_column(JSON().with_variant(JSONB, "postgresql"))


ParticleField = (
    BaseRecordField
    | Literal[
        "type",
        "data",
    ]
)
ParticleOrder = (
    BaseRecordOrder
    | Literal[
        "type",
        "-type",
    ]
)


class ParticleFilterArgs(BaseRecordFilterArgs[ParticleField, ParticleOrder], total=False):
    type: str | Sequence[str] | None
    type_contains: str | Sequence[str] | None
    type_prefix: str | Sequence[str] | None
    type_suffix: str | Sequence[str] | None


class ParticleFilter(BaseRecordFilter["Particle", ParticleField, ParticleOrder]):
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

    @override
    def matches(self, obj: Particle) -> bool:
        if not super().matches(obj):
            return False

        if self.type is not None:
            if obj.type not in util.as_sequence(self.type):
                return False
        if self.type_contains is not None:
            if not any(obj.type in type for type in util.as_sequence(self.type_contains)):
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

        return True

    @classmethod
    @override
    def _get_row_cls(cls) -> type[ParticleRow]:
        return ParticleRow

    @override
    def _get_search_content(self, obj: Particle) -> Mapping[str, str]:
        return {
            **super()._get_search_content(obj),
            "type": obj.type,
            "data": jsonify(obj.data),
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> Mapping[str, SQLColumnExpression[Any]]:
        columns = self._get_row_cls()

        match dialect:
            case DatabaseType.POSTGRES:
                data = cast(columns.data, Text)
            case DatabaseType.SQLITE:
                data = columns.data

        return {
            **super()._get_database_search_content(dialect),
            "type": columns.type,
            "data": data,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

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


class ParticleCreate(BaseRecordCreate):
    type: Annotated[str, CLIOption(str)]
    data: Annotated[JSONDict | BaseModel, CLIOption(str)]


class ParticleUpdate(BaseRecordUpdate, total=False):
    type: str
    data: JSONDict | BaseModel


UNKNOWN_TYPE: LiteralString = "__unknown__"


class ParticleData(ImmutableDataObject, ABC):
    model_config = ConfigDict(extra="allow")

    __type__: ClassVar[LiteralString]

    @classmethod
    def __init_subclass__(cls) -> None:
        if not hasattr(cls, "__type__") or not isinstance(cls.__type__, str):
            raise ValueError(f"{cls} must define `__type__` as a class attribute")


if TYPE_CHECKING:
    _T = TypeVar(
        "_T", bound=ParticleData | JSONDict, default=ParticleData | JSONDict, covariant=True
    )
else:
    _T = TypeVar("_T", default=ParticleData | JSONDict, covariant=True)


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

    @property
    def values(self) -> MappingProxyType[str, Any]:
        if not isinstance(self.data, dict):
            __dict__ = getattr(self.data, "__dict__", None)
            if __dict__ is None:
                return MappingProxyType({})

            return MappingProxyType(__dict__)

        return MappingProxyType(self.data)


class DynamicSiv(ImmutableDataObject):
    @abstractmethod
    def read(
        self, messages: AsyncIterable[Message]
    ) -> AsyncIterable[Result[Particle, ParticleError]]: ...


class Siv[T: Particle](DynamicSiv):
    @abstractmethod
    @override
    def read(self, messages: AsyncIterable[Message]) -> AsyncIterable[Result[T, ParticleError]]: ...


class MonoSiv[T: Particle](Siv[T]):
    @override
    async def read(
        self,
        messages: AsyncIterable[Message],
    ) -> AsyncIterable[Result[T, ParticleError]]:
        async for message in messages:
            yield self.parse(message)

    def parse(self, message: Message) -> Result[T, ParticleError]: ...
