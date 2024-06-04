from datetime import timedelta
from typing import Any, Mapping

from pydantic import Field, NonNegativeInt

from ceres.data import ImmutableDataObject, Name, PositiveTimeDelta
from ceres.schedule import Schedule


class Job(ImmutableDataObject):
    name: Name
    action: Name
    arguments: Mapping[Name, Any] | None = Field(None, validation_alias="args")
    schedule: Schedule = Field(discriminator="type")
    retries: NonNegativeInt = 0
    retry_delay: PositiveTimeDelta = timedelta(seconds=5)
