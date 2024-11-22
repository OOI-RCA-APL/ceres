from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, TypeVar, override

from ceres.data import ImmutableDataObject

_result_cls_generic_cache: dict[tuple[Any, ...], Any] = {}


class _Result:
    def __class_getitem__[ValueT, ErrorT](
        cls,
        /,
        params: tuple[type[ValueT], type[ErrorT]],
    ) -> Ok[ValueT] | Fail[ErrorT]:
        if params in _result_cls_generic_cache:
            return _result_cls_generic_cache[params]
        value = Ok[params[0]] | Fail[params[1]]
        _result_cls_generic_cache[params] = value
        return value  # type: ignore


class Ok[ValueT](ImmutableDataObject, _Result, frozen=True):  # type: ignore
    ok: Literal[True] = True
    value: ValueT

    def __init__(self, value: ValueT, **kwargs: Any) -> None:
        super().__init__(value=value)  # type: ignore

    __match_args__: tuple[Literal["value"]] = ("value",)

    @override
    def __str__(self) -> str:
        return f"Ok({self.value})"

    def __bool__(self) -> bool:
        return True


class Fail[ErrorT](ImmutableDataObject, _Result, frozen=True):  # type: ignore
    ok: Literal[False] = False
    error: ErrorT

    def __init__(self, error: ErrorT, **kwargs: Any) -> None:
        super().__init__(error=error)  # type: ignore

    __match_args__: tuple[Literal["error"]] = ("error",)  # type: ignore

    @override
    def __str__(self) -> str:
        return f"Fail({self.error})"

    def __bool__(self) -> bool:
        return False


if TYPE_CHECKING:
    _ValueT = TypeVar("_ValueT", covariant=True)
    _ErrorT = TypeVar("_ErrorT", covariant=True)
    Result = Ok[_ValueT] | Fail[_ErrorT]
else:
    Result = _Result
