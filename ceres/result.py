from typing import TYPE_CHECKING, Any, Literal, override

from ceres.data import ImmutableDataModel

_result_cls_generic_cache: dict[tuple[Any, ...], Any] = {}


class _Result:
    def __class_getitem__[ValueT, ErrorT](
        cls,
        /,
        params: tuple[type[ValueT], type[ErrorT]],
    ) -> Ok[ValueT] | Fail[ErrorT]:
        if params in _result_cls_generic_cache:
            return _result_cls_generic_cache[params]
        value_type = params[0]
        error_type = params[1]
        resolved = Ok.__class_getitem__(value_type) | Fail.__class_getitem__(error_type)
        _result_cls_generic_cache[params] = resolved
        return resolved  # type: ignore


class Ok[ValueT](ImmutableDataModel, _Result, frozen=True):  # type: ignore
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


class Fail[ErrorT](ImmutableDataModel, _Result, frozen=True):  # type: ignore
    ok: Literal[False] = False
    error: ErrorT

    def __init__(self, error: ErrorT, **kwargs: Any) -> None:
        super().__init__(error=error)  # type: ignore

    __match_args__: tuple[Literal["error"]] = ("error",)

    @override
    def __str__(self) -> str:
        return f"Fail({self.error})"

    def __bool__(self) -> bool:
        return False


if TYPE_CHECKING:
    type Result[V, E] = Ok[V] | Fail[E]
else:
    Result = _Result
