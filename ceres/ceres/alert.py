from datetime import datetime
from enum import Enum
from typing import Any, Mapping, cast
from uuid import UUID, uuid4

from pydantic import Field

from .address import ComponentAddress
from .data import ImmutableDataObject
from .datetime import utc


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Alert(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    source: ComponentAddress = cast(ComponentAddress, None)
    timestamp: datetime = Field(default_factory=utc)
    level: AlertLevel
    code: str
    info: Mapping[str, Any] = Field(default_factory=dict)
