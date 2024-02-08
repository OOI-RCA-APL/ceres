from abc import ABC, abstractmethod
from datetime import datetime
from re import Pattern
from typing import TYPE_CHECKING, Annotated, Any, Generic, Protocol, Sequence, TypeVar
from uuid import UUID

from pydantic import ConfigDict, Field
from sqlalchemy import (
    BinaryExpression,
    Delete,
    Select,
    SQLColumnExpression,
    Text,
    Update,
    cast,
    func,
    select,
)
from typing_extensions import Self, TypedDict, override

from ceres.address import Address, AddressSelector
from ceres.alert import Alert
from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta, jsonify
from ceres.database.enums import DatabaseType
from ceres.internal.cli.plumbing import CLIOption
from ceres.internal.utilities import StrEnum, as_sequence, escape_like_expression
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message, MessageContent, MessageDirection
from ceres.timing import utc
from ceres.user import UserRole

if TYPE_CHECKING:
    from ceres.component import Component
else:
    Component = object

_StatementT = TypeVar("_StatementT", bound=Select[tuple[Any, ...]] | Update | Delete)


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


class DatabaseFilter(Filter):
    @abstractmethod
    def apply(self, statement: _StatementT, dialect: DatabaseType) -> _StatementT: ...


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


class UserFilter(DatabaseFilter):
    id: Annotated[UUID | Sequence[UUID] | None, CLIOption(list[UUID] | None)] = Field(
        default=None,
        description="Filter by user ID(s)",
    )
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
    limit: Annotated[int | None, CLIOption(int | None)] = Field(
        default=None,
        description="Limit number of returned users.",
        ge=0,
        le=1000,
    )
    offset: Annotated[int | None, CLIOption(int | None)] = Field(
        default=None,
        description="Skip over a given number of users.",
        ge=0,
    )

    @override
    def apply(self, statement: _StatementT, dialect: DatabaseType) -> _StatementT:
        from ceres.internal.database.entities import UserEntity

        ids = select(UserEntity.id)

        if self.id is not None:
            ids = ids.where(UserEntity.id.in_(as_sequence(self.id)))
        if self.username is not None:
            ids = ids.where(UserEntity.username.in_(as_sequence(self.username)))
        if self.email is not None:
            # TODO: Normalize the email addresses before searching.
            ids = ids.where(UserEntity.email.in_(as_sequence(self.email)))
        if self.role is not None:
            ids = ids.where(UserEntity.role.in_(as_sequence(self.role)))
        if self.disabled is not None:
            ids = ids.where(UserEntity.disabled == self.disabled)

        match self.order:
            case None | UserOrder.USERNAME:
                ids = ids.order_by(UserEntity.username)
            case UserOrder.EMAIL:
                ids = ids.order_by(UserEntity.email)

        if self.limit is not None:
            ids = ids.limit(self.limit)
        if self.offset is not None and self.offset > 0:
            ids = ids.offset(self.offset)

        return statement.where(UserEntity.id.in_(ids))


class Addressable(Protocol):
    @property
    def address(self) -> Address: ...


_ObjectT = TypeVar("_ObjectT", bound=Addressable)


class AddressFilterArgs(TypedDict, total=False):
    address: AddressSelector | None


class AddressFilter(Filter, Generic[_ObjectT]):
    root: Annotated[Address, CLIOption(str | None)] = Address.root()
    address: Annotated[AddressSelector | None, CLIOption(str | None)] = None

    def matches(self, obj: _ObjectT) -> bool:
        if not self.root.contains(obj.address):
            return False

        if self.address is not None:
            if not self.address.matches(obj.address, self.root):
                return False

        return True


class ComponentFilterArgs(AddressFilterArgs, total=False):
    enabled: bool | None
    running: bool | None


class ComponentFilter(AddressFilter["Component"]):
    enabled: bool | None = None
    running: bool | None = None

    @override
    def matches(self, obj: "Component") -> bool:
        if not super().matches(obj):
            return False

        if self.enabled is not None and obj.enabled != self.enabled:
            return False

        if self.running is not None and obj.running != self.running:
            return False

        return True


class MessageOrder(StrEnum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class MessageFilterArgs(AddressFilterArgs, total=False):
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    direction: MessageDirection | None
    prefix: bytes | None
    suffix: bytes | None
    regex: Pattern[bytes] | None
    order: MessageOrder | None
    limit: int | None
    offset: int | None


class MessageFilter(AddressFilter[Message], DatabaseFilter):
    id: Annotated[UUID | Sequence[UUID] | None, CLIOption(list[UUID])] = None
    direction: Annotated[MessageDirection | None, CLIOption(MessageDirection | None)] = None
    search: Annotated[str | None, CLIOption(str | None)] = None
    search_case_sensitive: Annotated[bool, CLIOption(bool)] = False
    within: Annotated[PositiveTimeDelta | None, CLIOption(str | None)] = None
    after: Annotated[DateTime | None, CLIOption(datetime)] = None
    before: Annotated[DateTime | None, CLIOption(datetime)] = None
    prefix: Annotated[MessageContent | None, CLIOption(str | None)] = None
    suffix: Annotated[MessageContent | None, CLIOption(str | None)] = None
    regex: Annotated[Pattern[bytes] | None, CLIOption(str | None)] = None
    order: Annotated[MessageOrder | None, CLIOption(MessageOrder | None)] = None
    limit: Annotated[int | None, CLIOption(int | None)] = Field(default=None, ge=0)
    offset: Annotated[int | None, CLIOption(int | None)] = Field(default=None, ge=0)

    @override
    def matches(self, obj: Message) -> bool:
        if not super().matches(obj):
            return False

        if self.search is not None:
            search = self.search
            address = obj.address
            timestamp = _format_timestamp(obj.timestamp)
            direction = obj.direction
            content = obj.content
            if not self.search_case_sensitive:
                search = search.lower()
                content = obj.content.lower()
            if not (
                search in address
                or search in timestamp
                or search in direction
                or search.encode() in content
            ):
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

        if self.direction is not None:
            if obj.direction != self.direction:
                return False

        if self.prefix is not None:
            if not obj.content.startswith(self.prefix):
                return False
        if self.suffix is not None:
            if not obj.content.endswith(self.suffix):
                return False
        if self.regex is not None:
            if not self.regex.match(obj.content):
                return False

        return True

    @override
    def apply(self, statement: _StatementT, dialect: DatabaseType) -> _StatementT:
        from ceres.internal.database.entities import MessageEntity

        ids = select(MessageEntity.id)

        if self.id is not None:
            ids = ids.where(MessageEntity.id.in_(as_sequence(self.id)))

        if self.address is not None:
            ids = ids.where(
                self.address.matches_expression(MessageEntity.address, self.root),
            )

        if self.search:
            pattern = "%" + escape_like_expression(self.search) + "%"
            ids = ids.where(
                _format_sql_like(
                    MessageEntity.address,
                    pattern,
                    self.search_case_sensitive,
                )
                | _format_sql_like(
                    _format_sql_timestamp(MessageEntity.timestamp, dialect),
                    pattern,
                    self.search_case_sensitive,
                )
                | _format_sql_like(MessageEntity.direction, pattern, self.search_case_sensitive)
                | (
                    _format_sql_like(
                        MessageEntity.content,
                        pattern.encode(),
                        self.search_case_sensitive,
                    )
                    if dialect == DatabaseType.SQLITE
                    else _format_sql_like(
                        func.encode(MessageEntity.content, "escape"),
                        pattern.encode("utf-8").decode("unicode-escape"),
                        self.search_case_sensitive,
                    )
                ),
            )

        if self.within is not None:
            ids = ids.where(MessageEntity.timestamp >= utc() - self.within)
        if self.after is not None:
            ids = ids.where(MessageEntity.timestamp >= self.after)
        if self.before is not None:
            ids = ids.where(MessageEntity.timestamp < self.before)
        if self.direction is not None:
            ids = ids.where(MessageEntity.direction == self.direction)
        if self.prefix is not None:
            ids = ids.where(
                MessageEntity.content.like(escape_like_expression(self.prefix) + b"%"),
            )
        if self.suffix is not None:
            ids = ids.where(
                MessageEntity.content.like(b"%" + escape_like_expression(self.suffix)),
            )

        match self.order:
            case None | MessageOrder.OLD_TO_NEW:
                ids = ids.order_by(MessageEntity.timestamp)
            case MessageOrder.NEW_TO_OLD:
                ids = ids.order_by(MessageEntity.timestamp.desc())

        if self.limit is not None:
            ids = ids.limit(self.limit)
        if self.offset is not None and self.offset > 0:
            ids = ids.offset(self.offset)

        return statement.where(MessageEntity.id.in_(ids))


class AlertOrder(StrEnum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class AlertFilterArgs(TypedDict, total=False):
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    level: Level | Sequence[Level] | None
    code: str | Sequence[str] | None
    code_regex: Pattern[str] | None
    order: AlertOrder | None
    limit: int | None
    offset: int | None


class AlertFilter(AddressFilter[Alert], DatabaseFilter):
    search: Annotated[str | None, CLIOption(str | None)] = None
    search_case_sensitive: Annotated[bool, CLIOption(bool)] = False
    within: Annotated[PositiveTimeDelta | None, CLIOption(str | None)] = None
    after: Annotated[DateTime | None, CLIOption(datetime | None)] = None
    before: Annotated[DateTime | None, CLIOption(datetime | None)] = None
    level: Annotated[Level | Sequence[Level] | None, CLIOption(list[Level] | None)] = None
    code: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = None
    code_regex: Annotated[Pattern[str] | None, CLIOption(str | None)] = None
    order: Annotated[AlertOrder | None, CLIOption(AlertOrder | None)] = None
    limit: Annotated[int | None, CLIOption(int | None)] = Field(default=None, ge=0)
    offset: Annotated[int | None, CLIOption(int | None)] = Field(default=None, ge=0)

    @override
    def matches(self, obj: Alert) -> bool:
        if not super().matches(obj):
            return False

        if self.search is not None:
            search = self.search
            timestamp = _format_timestamp(obj.timestamp)
            level = obj.level
            code = obj.code
            info = jsonify(obj.info)

            if self.search_case_sensitive:
                search = search.lower()
                code = code.lower()
                info = info.lower()

            if not (search in timestamp or search in level or search in code or search in info):
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

        if self.level is not None:
            if obj.level not in as_sequence(self.level):
                return False

        if self.code is not None:
            if obj.code not in as_sequence(self.code):
                return False

        if self.code_regex is not None:
            if not self.code_regex.match(obj.code):
                return False

        return True

    @override
    def apply(self, statement: _StatementT, dialect: DatabaseType) -> _StatementT:
        from ceres.internal.database.entities import AlertEntity

        ids = select(AlertEntity.id)

        if self.address is not None:
            ids = ids.where(self.address.matches_expression(AlertEntity.address, self.root))

        if self.search is not None:
            pattern = "%" + escape_like_expression(self.search) + "%"
            ids = ids.where(
                _format_sql_like(
                    AlertEntity.address,
                    pattern,
                    self.search_case_sensitive,
                )
                | _format_sql_like(
                    _format_sql_timestamp(AlertEntity.timestamp, dialect),
                    pattern,
                    self.search_case_sensitive,
                )
                | _format_sql_like(AlertEntity.level, pattern, self.search_case_sensitive)
                | _format_sql_like(AlertEntity.code, pattern, self.search_case_sensitive)
                | _format_sql_like(
                    (
                        cast(AlertEntity.info, Text)
                        if dialect == DatabaseType.POSTGRES
                        else AlertEntity.info
                    ),
                    pattern,
                    self.search_case_sensitive,
                ),
            )

        if self.within is not None:
            ids = ids.where(AlertEntity.timestamp >= utc() - self.within)
        if self.after is not None:
            ids = ids.where(AlertEntity.timestamp >= self.after)
        if self.before is not None:
            ids = ids.where(AlertEntity.timestamp < self.before)
        if self.level is not None:
            if isinstance(self.level, Level):
                ids = ids.where(AlertEntity.level == self.level)
            else:
                ids = ids.where(AlertEntity.level.in_(self.level))
        if self.code is not None:
            if isinstance(self.code, str):
                ids = ids.where(AlertEntity.code == self.code)
            else:
                ids = ids.where(AlertEntity.code.in_(self.code))
        if self.code_regex is not None:
            ids = ids.where(AlertEntity.code.regexp_match(self.code_regex))

        match self.order:
            case None | AlertOrder.OLD_TO_NEW:
                ids = ids.order_by(AlertEntity.timestamp)
            case AlertOrder.NEW_TO_OLD:
                ids = ids.order_by(AlertEntity.timestamp.desc())

        if self.limit is not None:
            ids = ids.limit(self.limit)
        if self.offset is not None and self.offset > 0:
            ids = ids.offset(self.offset)

        return statement.where(AlertEntity.id.in_(ids))


class LogEntryOrder(StrEnum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class LogEntryFilterArgs(TypedDict, total=False):
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    level: Level | Sequence[Level] | None
    prefix: str | None
    suffix: str | None
    regex: Pattern[str] | None
    order: LogEntryOrder | None
    limit: int | None
    offset: int | None


class LogEntryFilter(AddressFilter[LogEntry], DatabaseFilter):
    search: Annotated[str | None, CLIOption(str | None)] = None
    search_case_sensitive: Annotated[bool, CLIOption(bool)] = False
    within: Annotated[PositiveTimeDelta | None, CLIOption(str | None)] = None
    after: Annotated[DateTime | None, CLIOption(datetime | None)] = None
    before: Annotated[DateTime | None, CLIOption(datetime | None)] = None
    level: Annotated[Level | Sequence[Level] | None, CLIOption(list[Level] | None)] = None
    prefix: Annotated[str | None, CLIOption(str | None)] = None
    suffix: Annotated[str | None, CLIOption(str | None)] = None
    regex: Annotated[Pattern[str] | None, CLIOption(str | None)] = None
    order: Annotated[LogEntryOrder | None, CLIOption(LogEntryOrder | None)] = None
    limit: Annotated[int | None, CLIOption(int | None)] = Field(default=None, ge=0)
    offset: Annotated[int | None, CLIOption(int | None)] = Field(default=None, ge=0)

    @override
    def matches(self, obj: LogEntry) -> bool:
        if not super().matches(obj):
            return False

        if self.search is not None:
            search = self.search
            timestamp = _format_timestamp(obj.timestamp)
            level = obj.level
            content = obj.content

            if not self.search_case_sensitive:
                search = search.lower()
                content = content.lower()

            if not (search in timestamp or search in level or search in content):
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

        if self.prefix is not None:
            if not obj.content.startswith(self.prefix):
                return False
        if self.suffix is not None:
            if not obj.content.endswith(self.suffix):
                return False
        if self.regex is not None:
            if not self.regex.match(obj.content):
                return False

        return True

    @override
    def apply(self, statement: _StatementT, dialect: DatabaseType) -> _StatementT:
        from ceres.internal.database.entities import LogEntryEntity

        ids = select(LogEntryEntity.id)

        if self.address is not None:
            ids = ids.where(self.address.matches_expression(LogEntryEntity.address, self.root))

        if self.search is not None:
            pattern = "%" + escape_like_expression(self.search) + "%"
            ids = ids.where(
                _format_sql_like(
                    LogEntryEntity.address,
                    pattern,
                    self.search_case_sensitive,
                )
                | _format_sql_like(
                    _format_sql_timestamp(LogEntryEntity.timestamp, dialect),
                    pattern,
                    self.search_case_sensitive,
                )
                | _format_sql_like(LogEntryEntity.level, pattern, self.search_case_sensitive)
                | _format_sql_like(
                    LogEntryEntity.content,
                    pattern,
                    self.search_case_sensitive,
                ),
            )

        if self.within is not None:
            ids = ids.where(LogEntryEntity.timestamp >= utc() - self.within)
        if self.after is not None:
            ids = ids.where(LogEntryEntity.timestamp >= self.after)
        if self.before is not None:
            ids = ids.where(LogEntryEntity.timestamp < self.before)
        if self.level is not None:
            if isinstance(self.level, Level):
                ids = ids.where(LogEntryEntity.level == self.level)
            else:
                ids = ids.where(LogEntryEntity.level.in_(self.level))
        if self.prefix is not None:
            ids = ids.where(
                LogEntryEntity.content.like(escape_like_expression(self.prefix) + "%"),
            )
        if self.suffix is not None:
            ids = ids.where(
                LogEntryEntity.content.like("%" + escape_like_expression(self.suffix)),
            )

        match self.order:
            case None | LogEntryOrder.OLD_TO_NEW:
                ids = ids.order_by(LogEntryEntity.timestamp)
            case LogEntryOrder.NEW_TO_OLD:
                ids = ids.order_by(LogEntryEntity.timestamp.desc())

        if self.limit is not None:
            ids = ids.limit(self.limit)
        if self.offset is not None and self.offset > 0:
            ids = ids.offset(self.offset)

        return statement.where(LogEntryEntity.id.in_(ids))


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
