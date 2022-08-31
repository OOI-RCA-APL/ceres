from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar, final

from pydantic.dataclasses import dataclass
from pydantic.generics import GenericModel

ValueT = TypeVar("ValueT")
ErrorT = TypeVar("ErrorT")


@final
@dataclass(frozen=True)
class Ok(Generic[ValueT, ErrorT]):
    value: ValueT
    ok: Literal[True] = True

    def __str__(self) -> str:
        return f"Ok({self.value})"

    def __bool__(self) -> bool:
        return True

    def dict(self) -> dict[str, Any]:
        return _OkModel(value=self.value).dict()

    def json(self, **dumps_kwargs: Any) -> str:
        return _OkModel(value=self.value).json(**dumps_kwargs)


@final
@dataclass(frozen=True)
class Fail(Generic[ValueT, ErrorT]):
    error: ErrorT
    ok: Literal[False] = False

    def __str__(self) -> str:
        return f"Fail({self.error})"

    def __bool__(self) -> bool:
        return False

    def dict(self) -> dict[str, Any]:
        return _ErrModel(error=self.error).dict()

    def json(self, **dumps_kwargs: Any) -> str:
        return _ErrModel(error=self.error).json(**dumps_kwargs)


Result = Ok[ValueT, ErrorT] | Fail[ValueT, ErrorT]


class _OkModel(GenericModel, Generic[ValueT]):
    ok: Literal[True] = True
    value: ValueT


class _ErrModel(GenericModel, Generic[ErrorT]):
    ok: Literal[False] = False
    error: ErrorT
