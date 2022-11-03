from dataclasses import field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Protocol, Union, runtime_checkable
from uuid import UUID, uuid4

from .utilities import vdc

if TYPE_CHECKING:
    from .internal.database.entity import AlertEntity

RawAlertLevel = Literal["info", "warning", "error"]


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    @classmethod
    def create_from(cls, raw: "AlertLevel" | RawAlertLevel) -> "AlertLevel":
        return cls(raw)


@runtime_checkable
class AlertLike(Protocol):
    @property
    def id(self) -> UUID:
        ...

    @property
    def origin_id(self) -> UUID:
        ...

    @property
    def timestamp(self) -> datetime:
        ...

    @property
    def kind(self) -> str:
        ...

    @property
    def level(self) -> AlertLevel:
        ...

    @property
    def info(self) -> dict[str, Any]:
        ...


@vdc(frozen=True)
class Alert:
    id: UUID = field(default_factory=uuid4)
    origin_id: UUID
    timestamp: datetime
    level: AlertLevel
    kind: str
    info: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create_from(other: Union[AlertLike, "AlertEntity"]) -> "Alert":
        return Alert(
            id=other.id,
            origin_id=other.origin_id,
            timestamp=other.timestamp,
            level=other.level,
            kind=other.kind,
            info=other.info,
        )
