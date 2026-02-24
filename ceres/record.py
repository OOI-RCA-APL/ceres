from __future__ import annotations

from functools import wraps
from typing import Any, TypeAlias, cast

from ceres.alert import Alert as Alert
from ceres.data import StrEnum
from ceres.item import ItemType
from ceres.logs import LogEntry as LogEntry
from ceres.message import Message as Message
from ceres.particle import Particle as Particle

Record: TypeAlias = Message | Particle[Any] | Alert | LogEntry


class RecordType(StrEnum):
    MESSAGE = "message"
    PARTICLE = "particle"
    ALERT = "alert"
    LOG_ENTRY = "log-entry"

    @property
    def cls(self) -> type[Record]:
        return cast("type[Record]", self.upcast().cls)

    def upcast(self) -> ItemType:
        return ItemType(self)


assert set(ItemType).issubset(ItemType)


_base__new__ = RecordType.__new__


@wraps(_base__new__)
def _override__new__(cls: type[RecordType], alias: str) -> RecordType:
    return _base__new__(cls, ItemType(alias))


RecordType.__new__ = _override__new__  # type: ignore
