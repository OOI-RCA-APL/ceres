from datetime import datetime
from enum import Enum
from re import Pattern
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Protocol,
    Sequence,
    TypedDict,
    TypeVar,
)

from pydantic import ConfigDict, Field
from typing_extensions import Self, override

from ceres.address import Address, AddressSelector
from ceres.alert import Alert
from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta, jsonify
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message, MessageDirection
from ceres.timing import utc

if TYPE_CHECKING:
    from ceres.component import Component
else:
    Component = object

Item = Message | Alert | LogEntry


class Filter(ImmutableDataObject):
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


class Addressable(Protocol):
    @property
    def address(self) -> Address:
        ...


_ObjectT = TypeVar("_ObjectT", bound=Addressable)


class ObjectFilterArgs(TypedDict, total=False):
    address: AddressSelector | None


class ObjectFilter(Generic[_ObjectT], Filter):
    address: AddressSelector | None = None

    def matches(self, obj: _ObjectT, root: Address = Address.root()) -> bool:
        if not root.contains(obj.address):
            return False

        if self.address is not None:
            if not self.address.matches(obj.address, root):
                return False

        return True


class ComponentFilterArgs(ObjectFilterArgs, total=False):
    enabled: bool | None
    running: bool | None


class ComponentFilter(ObjectFilter["Component"]):
    enabled: bool | None = None
    running: bool | None = None

    @override
    def matches(self, obj: "Component", root: Address = Address.root()) -> bool:
        if not super().matches(obj, root):
            return False

        if self.enabled is not None and obj.enabled != self.enabled:
            return False

        if self.running is not None and obj.running != self.running:
            return False

        return True


class MessageOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class MessageFilterArgs(ObjectFilterArgs, total=False):
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


class MessageFilter(ObjectFilter[Message]):
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    direction: MessageDirection | None = None
    prefix: bytes | None = None
    suffix: bytes | None = None
    regex: Pattern[bytes] | None = None
    order: MessageOrder | None = None
    limit: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)

    @override
    def matches(self, obj: Message, root: Address = Address.root()) -> bool:
        if not super().matches(obj, root):
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


class AlertOrder(str, Enum):
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


class AlertFilter(ObjectFilter[Alert]):
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    level: Level | Sequence[Level] | None = None
    code: str | Sequence[str] | None = None
    code_regex: Pattern[str] | None = None
    order: AlertOrder | None = None
    limit: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)

    @override
    def matches(self, obj: Alert, root: Address = Address.root()) -> bool:
        if not super().matches(obj, root):
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
            if isinstance(self.level, Level):
                if obj.level != self.level:
                    return False
            else:
                if obj.level not in self.level:
                    return False

        if self.code is not None:
            if isinstance(self.code, str):
                if obj.code != self.code:
                    return False
            else:
                if obj.code not in self.code:
                    return False

        if self.code_regex is not None:
            if not self.code_regex.match(obj.code):
                return False

        return True


class LogEntryOrder(str, Enum):
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


class LogEntryFilter(ObjectFilter[LogEntry]):
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    level: Level | Sequence[Level] | None = None
    prefix: str | None = None
    suffix: str | None = None
    regex: Pattern[str] | None = None
    order: LogEntryOrder | None = None
    limit: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)

    @override
    def matches(self, obj: LogEntry, root: Address = Address.root()) -> bool:
        if not super().matches(obj, root):
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
