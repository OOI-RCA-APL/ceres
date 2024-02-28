from datetime import datetime
from typing import Annotated, Any, Mapping
from typing_extensions import TypedDict
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from ceres.address import Address
from ceres.data import DateTime, ImmutableDataObject, JSONDict, jsonify
from ceres.internal.cli.plumbing import CLIOption
from ceres.level import Level
from ceres.timing import utc


class Alert(ImmutableDataObject):
    id: Annotated[UUID, CLIOption(UUID)] = Field(default_factory=uuid4)
    address: Annotated[Address, CLIOption(str)]
    timestamp: Annotated[DateTime, CLIOption(datetime)] = Field(default_factory=utc)
    level: Annotated[Level, CLIOption(Level)]
    code: Annotated[str, CLIOption(str)]
    info: Annotated[JSONDict, CLIOption(str)] = Field(default_factory=dict)

    @field_validator("info")
    def _validate_info(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            jsonify(value)
        except Exception:
            raise ValueError("info must be a JSON serializable mapping")

        return value


class AlertUpdate(TypedDict, total=False):
    address: Address
    timestamp: DateTime
    level: Level
    code: str
    info: JSONDict
