from typing import Any, Mapping
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from ceres.address import Address
from ceres.data import DateTime, ImmutableDataObject, JSONDict, jsonify
from ceres.level import Level
from ceres.timing import utc


class Alert(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    address: Address
    timestamp: DateTime = Field(default_factory=utc)
    level: Level
    code: str
    info: JSONDict = Field(default_factory=dict)

    @field_validator("info")
    def _validate_info(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            jsonify(value)
        except Exception:
            raise ValueError("info must be a JSON serializable mapping")

        return value
