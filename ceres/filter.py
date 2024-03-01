from abc import ABC, abstractmethod
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Generic,
    Iterable,
    Literal,
    Sequence,
    TypeVar,
)
from uuid import UUID

from pydantic import ConfigDict, Field, NonNegativeInt
from sqlalchemy import (
    BinaryExpression,
    ColumnExpressionArgument,
    Delete,
    Select,
    SQLColumnExpression,
    Update,
    func,
    select,
)
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql import expression
from typing_extensions import Self, TypedDict, override

from ceres.address import Address, AddressSelector
from ceres.alert import Alert
from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta
from ceres.database.enums import DatabaseType
from ceres.internal.cli.plumbing import CLIOption
from ceres.internal.utilities import StrEnum, as_sequence, escape_like_expression
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message, MessageContent, MessageDirection
from ceres.timing import utc
from ceres.user import User, UserRole

if TYPE_CHECKING:
    from ceres.component import Component
else:
    Component = object

_StatementT = TypeVar("_StatementT", bound=Select[tuple[Any, ...]] | Update | Delete)

if TYPE_CHECKING:
    from ceres.internal.database.entities import (
        AlertEntity,
        LogEntryEntity,
        MessageEntity,
        UserEntity,
    )
else:
    AlertEntity = object
    LogEntryEntity = object
    MessageEntity = object
    UserEntity = object

_Entity = UserEntity | MessageEntity | AlertEntity | LogEntryEntity


class Filter(ImmutableDataObject, ABC):
    model_config = ConfigDict(extra="ignore")

    def with_overrides(self, overrides: Self | None) -> Self:
        if overrides is None:
            return self

        update: dict[str, Any] = {}

        for attribute in overrides.model_fields_set:
            update[attribute] = getattr(overrides, attribute)

        return self.model_copy(update=update)

    def with_defaults(self, defaults: Self | None) -> Self:
        if defaults is None:
            return self

        update: dict[str, Any] = {}

        for attribute in defaults.model_fields_set:
            if attribute not in self.model_fields_set:
                update[attribute] = getattr(defaults, attribute)

        return self.model_copy(update=update)

    def is_empty(self) -> bool:
        return not all(getattr(self, field, None) is None for field in self.model_fields_set)


class ComponentFilterArgs(TypedDict, total=False):
    root: Annotated[Address, CLIOption(str | None)]
    address: Annotated[AddressSelector | None, CLIOption(str | None)]
    enabled: bool | None
    running: bool | None


class ComponentFilter(Filter):
    root: Annotated[Address, CLIOption(str | None)] = Address.root()
    address: Annotated[AddressSelector | None, CLIOption(str | None)] = None
    enabled: bool | None = None
    running: bool | None = None

    def matches(self, obj: "Component") -> bool:
        if self.address is not None:
            if not self.address.matches(obj.address, self.root):
                return False
        if self.enabled is not None and obj.enabled != self.enabled:
            return False
        if self.running is not None and obj.running != self.running:
            return False

        return True


class _DatabaseFilterArgs(TypedDict, total=False):
    search: str | None
    search_field: str | Sequence[str] | None
    id: UUID | Sequence[UUID] | None
    limit: NonNegativeInt | None
    offset: NonNegativeInt | None


_ObjectT = TypeVar("_ObjectT", bound=User | Message | Alert | LogEntry)


class _DatabaseFilter(Filter, Generic[_ObjectT], ABC):
    search: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter by text content of field(s) in `search-field`.",
    )
    search_field: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Field(s) matched by `search`. Defaults to all.",
    )
    id: Annotated[UUID | Sequence[UUID] | None, CLIOption(list[UUID])] = Field(
        default=None,
        description="Filter by ID(s).",
    )
    limit: Annotated[NonNegativeInt | None, CLIOption(int | None)] = Field(
        default=None,
        description="Limit the number of returned results.",
        ge=0,
    )
    offset: Annotated[NonNegativeInt | None, CLIOption(int | None)] = Field(
        default=None,
        description="Skip over a given number of results.",
        ge=0,
    )

    @abstractmethod
    def _get_entity_cls(self) -> type[_Entity]: ...

    @abstractmethod
    def _get_search_content(self, obj: _ObjectT) -> dict[str, str]: ...

    @abstractmethod
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, QueryableAttribute[str | bytes]]: ...

    def _get_database_search_encoded_fields(self) -> set[str]:
        return set()

    def matches(self, obj: _ObjectT) -> bool:
        if self.search is not None:
            values = self._get_search_content(obj)
            fields = values if self.search_field is None else as_sequence(self.search_field)
            matched = False
            for field in fields:
                value = values.get(field)
                if value is None:
                    continue

                if self.search in value:
                    matched = True
                    break

            if not matched:
                return False

        if self.id is not None:
            if obj.id not in as_sequence(self.id):
                return False

        return True

    def _get_where(self, dialect: DatabaseType) -> Iterable[ColumnExpressionArgument[Any]]:
        columns = self._get_entity_cls()
        encoded = self._get_database_search_encoded_fields()

        if self.search is not None:
            pattern = "%" + escape_like_expression(self.search) + "%"

            values = self._get_database_search_content(dialect)
            fields = values if self.search_field is None else as_sequence(self.search_field)
            condition: ColumnExpressionArgument[bool] | None = expression.false()

            for field in fields:
                value = values.get(field)
                if value is None:
                    continue

                if field in encoded:
                    condition |= value.like(pattern.encode("latin-1", "ignore"))
                else:
                    condition |= value.like(pattern)

            yield condition

        if self.id is not None:
            yield columns.id.in_(as_sequence(self.id))

    @abstractmethod
    def _get_order_by(self) -> ColumnExpressionArgument[Any]: ...

    def apply(self, statement: _StatementT, dialect: DatabaseType) -> _StatementT:
        columns = self._get_entity_cls()
        ids = (
            select(columns.id)
            .where(*self._get_where(dialect))
            .order_by(self._get_order_by())
            .limit(self.limit)
            .offset(self.offset)
        )

        if isinstance(statement, Update | Delete):
            return statement.where(columns.id.in_(ids))

        return statement.where(columns.id.in_(ids)).order_by(self._get_order_by())


class UserOrder(StrEnum):
    USERNAME = "username"
    EMAIL = "email"


class UserFilterArgs(TypedDict, total=False):
    id: UUID | Sequence[UUID] | None
    username: str | Sequence[str] | None
    email: str | Sequence[str] | None
    role: UserRole | Sequence[UserRole] | None
    disabled: bool | None
    order: UserOrder | None
    limit: int | None
    offset: int | None


class UserFilter(_DatabaseFilter[User]):
    username: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Filter by username(s).",
    )
    email: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Filter by user email(s).",
    )
    role: Annotated[UserRole | Sequence[UserRole] | None, CLIOption(list[UserRole] | None)] = Field(
        default=None,
        description="Filter by user role(s).",
    )
    disabled: Annotated[bool | None, CLIOption(bool | None)] = Field(
        default=None,
        description="Filter by disabled/enabled status.",
    )
    order: Annotated[UserOrder | None, CLIOption(UserOrder | None)] = Field(
        default=None,
        description="Specify order of resulting users.",
    )

    @override
    def _get_entity_cls(self) -> type[UserEntity]:
        from ceres.internal.database.entities import UserEntity

        return UserEntity

    @override
    def _get_search_content(self, obj: User) -> dict[str, str]:
        return {
            "username": obj.username,
            "email": obj.email,
            "role": obj.role,
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, QueryableAttribute[str | bytes]]:
        columns = self._get_entity_cls()

        return {
            "username": columns.username,
            "email": columns.email,
            "role": columns.role,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[ColumnExpressionArgument[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_entity_cls()

        if self.username is not None:
            yield columns.username.in_(as_sequence(self.username))
        if self.email is not None:
            yield columns.email.in_(as_sequence(self.email))
        if self.role is not None:
            yield columns.role.in_(as_sequence(self.role))
        if self.disabled is not None:
            yield columns.disabled == self.disabled

    @override
    def _get_order_by(self) -> ColumnExpressionArgument[Any]:
        columns = self._get_entity_cls()
        match self.order:
            case None | UserOrder.USERNAME:
                return columns.username
            case UserOrder.EMAIL:
                return columns.email


_ItemOrderInput = Literal["old-to-new", "new-to-old"]
_Item = Message | Alert | LogEntry
_ItemEntity = MessageEntity | AlertEntity | LogEntryEntity
_ItemT = TypeVar("_ItemT", bound=_Item)


class _ItemFilterArgs(_DatabaseFilterArgs, total=False):
    root: Address
    address: AddressSelector | None
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    order: _ItemOrderInput | None


class _ItemFilter(_DatabaseFilter[_ItemT], ABC):
    address: Annotated[AddressSelector | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter by associated address.",
    )
    root: Annotated[Address, CLIOption(str | None)] = Field(
        default=Address.root(),
        description="The root address relative `address` selectors are mapped to.",
    )
    within: Annotated[PositiveTimeDelta | None, CLIOption(str | None, metavar="DURATION")] = Field(
        default=None,
        description="Filter by age.",
    )
    after: Annotated[DateTime | None, CLIOption(datetime)] = Field(
        default=None,
        description="Filter by minimum timestamp.",
    )
    before: Annotated[DateTime | None, CLIOption(datetime)] = Field(
        default=None,
        description="Filter by maximum timestamp.",
    )
    order: Annotated[_ItemOrderInput | None, CLIOption(_ItemOrderInput | None)] = Field(
        default=None,
        description="Specify result order.",
    )

    @override
    def matches(self, obj: _ItemT) -> bool:  # type: ignore
        if not super().matches(obj):
            return False

        if self.address is not None:
            if not self.address.matches(obj.address, self.root):
                return False
        if self.within is not None:
            if obj.timestamp < utc() - self.within:
                return False
        if self.after is not None:
            if obj.timestamp < self.after:
                return False
        if self.before is not None:
            if obj.timestamp >= self.before:
                return False

        return True

    @abstractmethod
    def _get_entity_cls(self) -> type[_ItemEntity]: ...

    @override
    def _get_search_content(self, obj: _ItemT) -> dict[str, str]:
        return {
            "address": obj.address,
            "timestamp": _format_timestamp(obj.timestamp),
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, QueryableAttribute[str | bytes]]:
        columns = self._get_entity_cls()

        return {
            "address": columns.address,
            "timestamp": _format_sql_timestamp(columns.timestamp, dialect),
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[ColumnExpressionArgument[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_entity_cls()

        if self.id is not None:
            yield columns.id.in_(as_sequence(self.id))
        if self.address is not None:
            yield self.address.matches_expression(columns.address, self.root)
        if self.within is not None:
            yield columns.timestamp >= utc() - self.within
        if self.after is not None:
            yield columns.timestamp >= self.after
        if self.before is not None:
            yield columns.timestamp < self.before

    @override
    def _get_order_by(self) -> ColumnExpressionArgument[Any]:
        columns = self._get_entity_cls()

        match self.order:
            case None | "old-to-new":
                return columns.timestamp
            case "new-to-old":
                return columns.timestamp.desc()

        raise ValueError("invalid order type")


class MessageOrder(StrEnum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class MessageFilterArgs(_ItemFilterArgs, total=False):
    direction: MessageDirection | None
    content_contains: MessageContent | None
    content_prefix: MessageContent | None
    content_suffix: MessageContent | None
    order: MessageOrder | None  # type: ignore


class MessageFilter(_ItemFilter[Message]):
    direction: Annotated[MessageDirection | None, CLIOption(MessageDirection | None)] = Field(
        default=None,
        description="Filter by message direction.",
    )
    content_contains: Annotated[MessageContent | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only messages with content that contains the given bytes.",
    )
    content_prefix: Annotated[MessageContent | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only messages with content that starts with the given bytes.",
    )
    content_suffix: Annotated[MessageContent | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only messages with content that ends with the given bytes.",
    )
    order: Annotated[MessageOrder | None, CLIOption(MessageOrder | None)] = Field(
        None,
        description="Specify result order.",
    )

    @override
    def matches(self, obj: Message) -> bool:
        if not super().matches(obj):
            return False

        if self.direction is not None:
            if obj.direction not in as_sequence(self.direction):
                return False
        if self.content_contains is not None:
            if self.content_contains not in obj.content:
                return False
        if self.content_prefix is not None:
            if not obj.content.startswith(self.content_prefix):
                return False
        if self.content_suffix is not None:
            if not obj.content.endswith(self.content_suffix):
                return False

        return True

    @override
    def _get_entity_cls(self) -> type[MessageEntity]:
        from ceres.internal.database.entities import MessageEntity

        return MessageEntity

    @override
    def _get_search_content(self, obj: Message) -> dict[str, str]:
        return {
            **super()._get_search_content(obj),
            "direction": obj.direction,
            "content": obj.content.decode("latin-1", "ignore"),
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, QueryableAttribute[str | bytes]]:
        columns = self._get_entity_cls()

        return {
            **super()._get_database_search_content(dialect),
            "direction": columns.direction,
            "content": columns.content,
        }

    @override
    def _get_database_search_encoded_fields(self) -> set[str]:
        return {"content"}

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[ColumnExpressionArgument[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_entity_cls()

        if self.direction is not None:
            yield columns.direction == self.direction
        if self.content_contains is not None:
            yield columns.content.like(b"%" + escape_like_expression(self.content_contains) + b"%")
        if self.content_prefix is not None:
            yield columns.content.like(escape_like_expression(self.content_prefix) + b"%")
        if self.content_suffix is not None:
            yield columns.content.like(b"%" + escape_like_expression(self.content_suffix))


class AlertOrder(StrEnum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class AlertFilterArgs(_ItemFilterArgs, total=False):
    level: Level | Sequence[Level] | None
    code: str | Sequence[str] | None
    code_contains: str | None
    code_prefix: str | None
    code_suffix: str | None
    order: AlertOrder | None  # type: ignore


class AlertFilter(_ItemFilter[Alert]):
    level: Annotated[Level | Sequence[Level] | None, CLIOption(list[Level] | None)] = Field(
        default=None,
        description="Filter by alert level(s).",
    )
    code: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Filter by alert code(s).",
    )
    code_contains: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only alerts with codes that contain the given string.",
    )
    code_prefix: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only alerts with codes that start with the given string.",
    )
    code_suffix: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only alerts with codes that end with the given string.",
    )
    order: Annotated[AlertOrder | None, CLIOption(AlertOrder | None)] = Field(
        default=None,
        description="Specify result order.",
    )

    @override
    def matches(self, obj: Alert) -> bool:
        if not super().matches(obj):
            return False

        if self.level is not None:
            if obj.level not in as_sequence(self.level):
                return False
        if self.code is not None:
            if obj.code not in as_sequence(self.code):
                return False
        if self.code_contains is not None:
            if self.code_contains not in obj.code:
                return False
        if self.code_prefix is not None:
            if not obj.code.startswith(self.code_prefix):
                return False
        if self.code_suffix is not None:
            if not obj.code.endswith(self.code_suffix):
                return False

        return True

    @override
    def _get_entity_cls(self) -> type[AlertEntity]:
        from ceres.internal.database.entities import AlertEntity

        return AlertEntity

    @override
    def _get_search_content(self, obj: Alert) -> dict[str, str]:
        return {
            **super()._get_search_content(obj),
            "level": obj.level,
            "code": obj.code,
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, QueryableAttribute[str | bytes]]:
        columns = self._get_entity_cls()

        return {
            **super()._get_database_search_content(dialect),
            "level": columns.level,
            "code": columns.code,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[ColumnExpressionArgument[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_entity_cls()

        if self.level is not None:
            yield columns.level.in_(as_sequence(self.level))
        if self.code is not None:
            yield columns.code.in_(as_sequence(self.code))
        if self.code_contains is not None:
            yield columns.code.like("%" + escape_like_expression(self.code_contains) + "%")
        if self.code_prefix is not None:
            yield columns.code.like(escape_like_expression(self.code_prefix) + "%")
        if self.code_suffix is not None:
            yield columns.code.like("%" + escape_like_expression(self.code_suffix))


class LogEntryOrder(StrEnum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class LogEntryFilterArgs(_ItemFilterArgs, total=False):
    level: Level | Sequence[Level] | None
    content_contains: str | None
    content_prefix: str | None
    content_suffix: str | None
    order: LogEntryOrder | None  # type: ignore


class LogEntryFilter(_ItemFilter[LogEntry]):
    level: Annotated[Level | Sequence[Level] | None, CLIOption(list[Level] | None)] = Field(
        default=None,
        description="Filter by log level(s).",
    )
    content_contains: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only log entries with content that contain the given string.",
    )
    content_prefix: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only log entries with content that starts with the given string.",
    )
    content_suffix: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only log entries with content that ends with the given string.",
    )
    order: Annotated[LogEntryOrder | None, CLIOption(LogEntryOrder | None)] = Field(
        default=None,
        description="Specify result order.",
    )

    @override
    def matches(self, obj: LogEntry) -> bool:
        if not super().matches(obj):
            return False

        if self.level is not None:
            if obj.level not in as_sequence(self.level):
                return False
        if self.content_contains is not None:
            if self.content_contains not in obj.content:
                return False
        if self.content_prefix is not None:
            if not obj.content.startswith(self.content_prefix):
                return False
        if self.content_suffix is not None:
            if not obj.content.endswith(self.content_suffix):
                return False

        return True

    @override
    def _get_entity_cls(self) -> type[LogEntryEntity]:
        from ceres.internal.database.entities import LogEntryEntity

        return LogEntryEntity

    @override
    def _get_search_content(self, obj: LogEntry) -> dict[str, str]:
        return {
            **super()._get_search_content(obj),
            "level": obj.level,
            "content": obj.content,
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, QueryableAttribute[str | bytes]]:
        columns = self._get_entity_cls()

        return {
            **super()._get_database_search_content(dialect),
            "level": columns.level,
            "content": columns.content,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[ColumnExpressionArgument[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_entity_cls()

        if self.level is not None:
            yield columns.level.in_(as_sequence(self.level))
        if self.content_contains is not None:
            yield columns.content.like("%" + escape_like_expression(self.content_contains) + "%")
        if self.content_prefix is not None:
            yield columns.content.like(escape_like_expression(self.content_prefix) + "%")
        if self.content_suffix is not None:
            yield columns.content.like("%" + escape_like_expression(self.content_suffix))


class StatisticsFilterArgs(TypedDict, total=False):
    address: AddressSelector | None
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None


class StatisticsFilter(Filter):
    root: Address | None = None
    address: AddressSelector | None = None
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m-%d %H:%M:%f")


def _format_sql_like(
    expression: SQLColumnExpression[Any],
    pattern: str | bytes,
    case_sensitive: bool = False,
) -> BinaryExpression[bool]:
    if case_sensitive:
        return expression.like(pattern)
    return expression.ilike(pattern)


def _format_sql_timestamp(
    timestamp: SQLColumnExpression[datetime],
    dialect: DatabaseType,
) -> Any:
    match dialect:
        case DatabaseType.SQLITE:
            return timestamp
        case DatabaseType.POSTGRES:
            return func.to_char(timestamp, "YYYY-MM-DD HH24:MI:SS.US")
