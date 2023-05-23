from typing import Any, Mapping
from uuid import UUID, uuid4

from pydantic import Field, validator

from ceres.address import Address
from ceres.data import DateTime, ImmutableDataObject, jsonify
from ceres.level import Level
from ceres.timing import utc


class Alert(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    source: Address
    timestamp: DateTime = Field(default_factory=utc)
    level: Level
    code: str
    info: Mapping[str, Any] = Field(default_factory=dict)

    @validator("info")
    def _validate_info(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            jsonify(value)
        except Exception:
            raise ValueError("info must be a JSON serializable mapping")

        return value
