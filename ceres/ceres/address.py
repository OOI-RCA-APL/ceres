import re
from re import Pattern
from typing import Any, final

from typing_extensions import Self

from .types import NAME_REGEX, Name


class _RegexStr(str):
    regex: Pattern[str] = re.compile(r".+")

    @classmethod
    def __get_validators__(cls) -> Any:
        yield cls.validate

    def __new__(cls, obj: str, /) -> Self:
        if isinstance(obj, cls):
            return obj

        return str.__new__(cls, cls.validate(obj))

    @classmethod
    def validate(cls, value: str) -> Self:
        if isinstance(value, cls):
            return value

        if cls.regex.match(value) is None:
            raise ValueError(f"must match regex {cls.regex.pattern}")

        return str.__new__(cls, value)


@final
class ComponentAddress(_RegexStr):
    regex = re.compile(rf"^{NAME_REGEX.pattern[1:-1]}\.{NAME_REGEX.pattern[1:-1]}$")

    @classmethod
    def create(cls, unit: str, component: str, /) -> Self:
        return cls(f"{unit}.{component}")

    @property
    def unit(self) -> Name:
        return self[: self.index(".")]

    @property
    def component(self) -> Name:
        return self[self.index(".") + 1 :]

    @property
    def name(self) -> Name:
        return self.component
