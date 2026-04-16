from functools import wraps
from typing import Any, TypeAlias, cast

from ceres.alert import Alert as Alert
from ceres.data import StrEnum
from ceres.item import ItemType
from ceres.logs import LogEntry as LogEntry
from ceres.message import Message as Message
from ceres.particle import Particle as Particle

__all__ = [
    "Record",
    "RecordType",
]

Record: TypeAlias = Message | Particle[Any] | Alert | LogEntry
"""Union of entities that originate from a component as part of normal data collection.

Records are the time-series outputs a component emits during operation, namely raw
`Message` payloads from connections, parsed `Particle` data, `Alert` notifications, and
`LogEntry` rows. Workspace, user, and configuration entities are excluded.
"""


class RecordType(StrEnum):
    """Discriminator for the variants of `Record`.

    `RecordType` is a strict subset of `ItemType`, every record type also exists as an item
    type and the two enums share their string values to keep cross-references unambiguous.
    """

    MESSAGE = "message"
    PARTICLE = "particle"
    ALERT = "alert"
    LOG_ENTRY = "log-entry"

    @property
    def cls(self) -> type[Record]:
        """Return the concrete `Record` subclass associated with this variant."""
        return cast("type[Record]", self.upcast().cls)

    def upcast(self) -> ItemType:
        """Return the equivalent `ItemType` value, widening from record into item."""
        return ItemType(self)


# Sanity check that every `RecordType` value also exists in `ItemType`, the two enums must
# stay aligned because `upcast` and `__new__` route through `ItemType`.
assert set(RecordType).issubset(ItemType)


_base__new__ = RecordType.__new__


@wraps(_base__new__)
def _override__new__(cls: type[RecordType], alias: str) -> RecordType:
    # Route construction through `ItemType` first, this lets `RecordType` accept any alias
    # that `ItemType` understands (such as plural or alternate forms).
    return _base__new__(cls, ItemType(alias))


RecordType.__new__ = _override__new__  # type: ignore
