from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Protocol, Union, runtime_checkable
from uuid import UUID, uuid4

from pydantic import Field
from typing_extensions import Self

from .data import ImmutableDataObject
from .datetime import utc

if TYPE_CHECKING:
    from .internal.database.entity import AlertEntity

RawAlertLevel = Literal["info", "warning", "error"]


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    @classmethod
    def create_from(cls, raw: Self | RawAlertLevel) -> Self:
        return cls(raw)


@runtime_checkable
class AlertLike(Protocol):
    @property
    def id(self) -> UUID:
        ...

    @property
    def component_id(self) -> UUID:
        ...

    @property
    def timestamp(self) -> datetime:
        ...

    @property
    def code(self) -> str:
        ...

    @property
    def level(self) -> AlertLevel:
        ...

    @property
    def info(self) -> dict[str, Any]:
        ...


class Alert(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    component_id: UUID = UUID(int=0)
    timestamp: datetime = Field(default_factory=utc)
    level: AlertLevel
    code: str
    info: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create_from(cls, other: Union[AlertLike, "AlertEntity"]) -> Self:
        return cls(
            id=other.id,
            component_id=other.component_id,
            timestamp=other.timestamp,
            level=other.level,
            code=other.code,
            info=other.info,
        )
