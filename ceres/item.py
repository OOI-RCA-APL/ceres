from functools import wraps
from typing import TypeAlias, cast

from ceres.alert import Alert as Alert
from ceres.data import StrEnum
from ceres.entity import EntityType
from ceres.logs import LogEntry as LogEntry
from ceres.message import Message as Message
from ceres.particle import Particle as Particle
from ceres.variable import Variable as Variable

__all__ = [
    "Item",
    "ItemType",
]

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

_base__new__ = ItemType.__new__


@wraps(_base__new__)
def _override__new__(cls: type[ItemType], value: str) -> ItemType:
    return _base__new__(cls, EntityType(value))


ItemType.__new__ = _override__new__
