from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from .internal.utilities import MaybeMapped


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


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


@dataclass(kw_only=True, frozen=True)
class Alert:
    id: UUID
    origin_id: UUID
    timestamp: datetime
    kind: str
    level: AlertLevel
    info: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create_from(other: AlertLike) -> Alert:
        return Alert(
            id=other.id,
            origin_id=other.origin_id,
            timestamp=other.timestamp,
            kind=other.kind,
            level=other.level,
            info=other.info,
        )
