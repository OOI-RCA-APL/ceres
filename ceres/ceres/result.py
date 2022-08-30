from __future__ import annotations

from typing import Generic, Literal, TypeVar

from .data import GenericDataObject

ValueT = TypeVar("ValueT")
ErrorT = TypeVar("ErrorT")


class Ok(GenericDataObject, Generic[ValueT]):
    class Config:
        frozen = True
        allow_arbitrary_types = True

    ok: Literal[True] = True
    value: ValueT

    @classmethod
    def create(cls, value: ValueT) -> Ok[ValueT]:
        return Ok(value=value)


class Err(GenericDataObject, Generic[ErrorT]):
    class Config:
        frozen = True
        allow_arbitrary_types = True

    ok: Literal[False] = False
    error: ErrorT

    @classmethod
    def create(cls, error: ErrorT) -> Err[ErrorT]:
        return Err(error=error)


Result = Ok[ValueT] | Err[ErrorT]
