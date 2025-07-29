from __future__ import annotations

from functools import wraps
from typing import TypeAlias, cast

from ceres.alert import Alert as Alert
from ceres.data import StrEnum
from ceres.entity import EntityType
from ceres.logs import LogEntry as LogEntry
from ceres.message import Message as Message
from ceres.particle import Particle as Particle
from ceres.variable import Variable as Variable

Item: TypeAlias = Message | Particle | Alert | LogEntry | Variable


class ItemType(StrEnum):
    MESSAGE = "message"
    PARTICLE = "particle"
    ALERT = "alert"
    LOG_ENTRY = "log-entry"
    VARIABLE = "variable"

    @property
    def cls(self) -> type[Item]:
        return cast("type[Item]", self.upcast().cls)

    def upcast(self) -> EntityType:
        return EntityType(self)


assert set(ItemType).issubset(EntityType)

__new = ItemType.__new__


@wraps(__new)
def __new_override(cls: type[ItemType], value: str) -> ItemType:
    return __new(cls, EntityType(value))


ItemType.__new__ = __new_override  # type: ignore
