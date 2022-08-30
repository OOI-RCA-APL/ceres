from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic.dataclasses import dataclass

from .data import GenericDataObject

ValueT = TypeVar("ValueT")
ErrorT = TypeVar("ErrorT")


@dataclass(frozen=True)
class Ok(Generic[ValueT]):
    value: ValueT
    ok: Literal[True] = True

    def __str__(self) -> str:
        return f"Ok({self.value})"

    def dict(self) -> dict[str, Any]:
        return OkModel(value=self.value).dict()

    def json(self, **dumps_kwargs: Any) -> str:
        return OkModel(value=self.value).json(**dumps_kwargs)


@dataclass(frozen=True)
class Fail(Generic[ErrorT]):
    error: ErrorT
    ok: Literal[False] = False

    def __str__(self) -> str:
        return f"Fail({self.error})"

    def dict(self) -> dict[str, Any]:
        return ErrModel(error=self.error).dict()

    def json(self, **dumps_kwargs: Any) -> str:
        return ErrModel(error=self.error).json(**dumps_kwargs)


Result = Ok[ValueT] | Fail[ErrorT]


class OkModel(GenericDataObject, Generic[ValueT]):
    ok: Literal[True] = True
    value: ValueT


class ErrModel(GenericDataObject, Generic[ErrorT]):
    ok: Literal[False] = False
    error: ErrorT
