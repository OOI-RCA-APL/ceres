from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

from pydantic.generics import GenericModel

from .data import ImmutableDataObject

_ValueT = TypeVar("_ValueT", covariant=True)
_ErrorT = TypeVar("_ErrorT", covariant=True)

_class_getitem_cache: dict[tuple[Any, ...], Any] = {}


class __Result:
    """
    This is a workaround for https://github.com/pydantic/pydantic/issues/1194. This can probably be
    removed once Pydantic 2.0 comes out and "GenericModel" is no longer needed.
    """

    def __class_getitem__(
        cls,
        /,
        params: tuple[type[_ValueT], type[_ErrorT]],
    ) -> "Ok[_ValueT] | Fail[_ErrorT]":
        if params in _class_getitem_cache:
            return _class_getitem_cache[params]
        value = Ok[params[0]] | Fail[params[1]]  # type: ignore
        _class_getitem_cache[params] = value
        return value  # type: ignore


__Result.__name__ = "Result"
__Result.__qualname__ = __Result.__qualname__.replace("__Result", "Result")


class Ok(ImmutableDataObject, GenericModel, Generic[_ValueT], __Result):
    ok: Literal[True] = True
    value: _ValueT

    def __init__(self, value: _ValueT, **kwargs: Any) -> None:
        super().__init__(value=value)  # type: ignore

    __match_args__: tuple[Literal["value"]] = ("value",)  # type: ignore

    def __str__(self) -> str:
        return f"Ok({self.value})"

    def __bool__(self) -> bool:
        return True


class Fail(ImmutableDataObject, GenericModel, Generic[_ErrorT], __Result):
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
    Result = __Result
