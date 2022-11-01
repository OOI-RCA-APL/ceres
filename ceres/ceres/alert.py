from dataclasses import field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic.dataclasses import dataclass as validated_dataclass

from .internal.utilities import MaybeMapped

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
    def id(self) -> MaybeMapped[UUID]:
        ...

    @property
    def origin_id(self) -> MaybeMapped[UUID]:
        ...

    @property
    def timestamp(self) -> MaybeMapped[datetime]:
        ...

    @property
    def kind(self) -> MaybeMapped[str]:
        ...

    @property
    def level(self) -> MaybeMapped[AlertLevel]:
        ...

    @property
    def info(self) -> MaybeMapped[dict[str, Any]]:
        ...


@validated_dataclass(kw_only=True, frozen=True)
class Alert:
    id: UUID = field(default_factory=uuid4)
    origin_id: UUID
    timestamp: datetime
    level: AlertLevel
    kind: str
    info: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create_from(other: AlertLike) -> "Alert":
        return Alert(
            id=other.id,
            origin_id=other.origin_id,
            timestamp=other.timestamp,
            level=other.level,
            kind=other.kind,
            info=other.info,
        )
