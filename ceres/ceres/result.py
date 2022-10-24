from __future__ import annotations

from dataclasses import field
from typing import Generic, Literal, TypeVar, final

from pydantic.dataclasses import dataclass
from pydantic.generics import GenericModel

ValueT = TypeVar("ValueT")
ErrorT = TypeVar("ErrorT")


@final
@dataclass(frozen=True)
class Ok(Generic[ValueT, ErrorT]):
    __match_args__ = ("value",)

    ok: Literal[True] = field(default=True, init=False)
    value: ValueT

    def __str__(self) -> str:
        return f"Ok({self.value})"

    def __bool__(self) -> bool:
        return True


@final
@dataclass(frozen=True)
class Fail(Generic[ValueT, ErrorT]):
    __match_args__ = ("error",)

    ok: Literal[False] = field(default=False, init=False)
    error: ErrorT

    def __str__(self) -> str:
        return f"Fail({self.error})"

    def __bool__(self) -> bool:
        return False


Result = Ok[ValueT, ErrorT] | Fail[ValueT, ErrorT]


class _OkModel(GenericModel, Generic[ValueT]):
    ok: Literal[True] = True
    value: ValueT


class _ErrModel(GenericModel, Generic[ErrorT]):
    ok: Literal[False] = False
    error: ErrorT
