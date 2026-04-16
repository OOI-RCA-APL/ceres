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
"""Union of record types that flow through the system as user-visible items."""


class ItemType(StrEnum):
    """Discriminator identifying which concrete record type an `Item` is.

    `ItemType` is a strict subset of `EntityType` covering only the user-facing record
    kinds, it upcasts to `EntityType` when interaction with the broader entity system
    is required.
    """

    MESSAGE = "message"
    PARTICLE = "particle"
    ALERT = "alert"
    LOG_ENTRY = "log-entry"
    VARIABLE = "variable"

    @property
    def cls(self) -> type[Item]:
        """Return the concrete record class associated with this item type."""
        return cast("type[Item]", self.upcast().cls)

    def upcast(self) -> EntityType:
        """Return the matching `EntityType` value for this item type."""
        return EntityType(self)


assert set(ItemType).issubset(EntityType)

_base__new__ = ItemType.__new__


@wraps(_base__new__)
def _override__new__(cls: type[ItemType], value: str) -> ItemType:
    # Route construction through `EntityType` so aliases accepted there also resolve here.
    return _base__new__(cls, EntityType(value))


ItemType.__new__ = _override__new__
