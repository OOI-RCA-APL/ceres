from dataclasses import field
from typing import TYPE_CHECKING, Generic, Literal, TypeVar, final

from .data import DataObject

_ValueT = TypeVar("_ValueT")
_ErrorT = TypeVar("_ErrorT")


@final
class Ok(Generic[_ValueT, _ErrorT], DataObject, kw_only=False, frozen=True):
    value: _ValueT
    ok: Literal[True] = field(default=True, init=False)

    if TYPE_CHECKING:
        __match_args__: tuple[Literal["value"], Literal["ok"]] = ("value", "ok")  # type: ignore

    def __str__(self) -> str:
        return f"Ok({self.value})"

    def __bool__(self) -> bool:
        return True


@final
class Fail(Generic[_ValueT, _ErrorT], DataObject, kw_only=False, frozen=True):
    error: _ErrorT
    ok: Literal[False] = field(default=False, init=False)

    if TYPE_CHECKING:
        __match_args__: tuple[Literal["error"], Literal["ok"]] = ("error", "ok")  # type: ignore

    def __str__(self) -> str:
        return f"Fail({self.error})"

    def __bool__(self) -> bool:
        return False


Result = Ok[_ValueT, _ErrorT] | Fail[_ValueT, _ErrorT]
