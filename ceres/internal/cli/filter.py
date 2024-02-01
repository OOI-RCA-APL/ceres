from typing import Any

from pydantic import field_validator

from ceres.data import ImmutableDataObject
from ceres.filter import AlertFilter, LogEntryFilter, MessageFilter, UserFilter


class _BaseFilterOptions(ImmutableDataObject):
    @field_validator("*")
    def __validate_empty_list_as_none(cls, value: Any) -> Any:
        if isinstance(value, list) and not value:
            return None

        return value


class CLIUserFilter(UserFilter, _BaseFilterOptions):
    pass


class CLIMessageFilter(MessageFilter, _BaseFilterOptions):
    pass


class CLIAlertFilter(AlertFilter, _BaseFilterOptions):
    pass


class CLILogEntryFilter(LogEntryFilter, _BaseFilterOptions):
    pass
