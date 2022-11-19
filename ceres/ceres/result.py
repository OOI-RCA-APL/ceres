from typing import Any, Generic, Literal, TypeVar

from pydantic.generics import GenericModel

from .data import FrozenDataObject

_ValueT = TypeVar("_ValueT")
_ErrorT = TypeVar("_ErrorT")


class Ok(FrozenDataObject, GenericModel, Generic[_ValueT]):
    ok: Literal[True] = True
    value: _ValueT

    def __init__(self, value: _ValueT, **kwargs: Any) -> None:
        super().__init__(value=value)  # type: ignore

    __match_args__: tuple[Literal["value"]] = ("value",)  # type: ignore

    def __str__(self) -> str:
        return f"Ok({self.value})"

    def __bool__(self) -> bool:
        return True


class Fail(FrozenDataObject, GenericModel, Generic[_ErrorT]):
    ok: Literal[False] = False
    error: _ErrorT

    def __init__(self, error: _ErrorT, **kwargs: Any) -> None:
        super().__init__(error=error)  # type: ignore

    __match_args__: tuple[Literal["error"]] = ("error",)  # type: ignore

    def __str__(self) -> str:
        return f"Fail({self.error})"

    def __bool__(self) -> bool:
        return False


Result = Ok[_ValueT] | Fail[_ErrorT]
