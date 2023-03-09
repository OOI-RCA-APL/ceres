from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

from pydantic.generics import GenericModel

from ceres.data import ImmutableDataObject

_ValueT = TypeVar("_ValueT", covariant=True)
_ErrorT = TypeVar("_ErrorT", covariant=True)

_result_cls_generic_cache: dict[tuple[Any, ...], Any] = {}


class _Result:
    """
    This is a workaround for https://github.com/pydantic/pydantic/issues/1194. This can probably be
    removed once Pydantic 2.0 comes out and "GenericModel" is no longer needed.
    """

    def __class_getitem__(
        cls,
        /,
        params: tuple[type[_ValueT], type[_ErrorT]],
    ) -> "Ok[_ValueT] | Fail[_ErrorT]":
        if params in _result_cls_generic_cache:
            return _result_cls_generic_cache[params]
        value = Ok[params[0]] | Fail[params[1]]  # type: ignore
        _result_cls_generic_cache[params] = value
        return value  # type: ignore


class Ok(ImmutableDataObject, GenericModel, Generic[_ValueT], _Result):
    ok: Literal[True] = True
    value: _ValueT

    def __init__(self, value: _ValueT, **kwargs: Any) -> None:
        super().__init__(value=value)  # type: ignore

    __match_args__: tuple[Literal["value"]] = ("value",)  # type: ignore

    def __str__(self) -> str:
        return f"Ok({self.value})"

    def __bool__(self) -> bool:
        return True


class Fail(ImmutableDataObject, GenericModel, Generic[_ErrorT], _Result):
    ok: Literal[False] = False
    error: _ErrorT

    def __init__(self, error: _ErrorT, **kwargs: Any) -> None:
        super().__init__(error=error)  # type: ignore

    __match_args__: tuple[Literal["error"]] = ("error",)  # type: ignore

    def __str__(self) -> str:
        return f"Fail({self.error})"

    def __bool__(self) -> bool:
        return False


if TYPE_CHECKING:
    Result = Ok[_ValueT] | Fail[_ErrorT]
else:
    Result = _Result
