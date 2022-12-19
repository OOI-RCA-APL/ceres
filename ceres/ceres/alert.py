from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4

from pydantic import Field

from .data import ImmutableDataObject
from .datetime import utc
from .internal.utilities import UNSET_UUID


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Alert(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    component_id: UUID = UNSET_UUID
    timestamp: datetime = Field(default_factory=utc)
    level: AlertLevel
    code: str
    info: Mapping[str, Any] = Field(default_factory=dict)
