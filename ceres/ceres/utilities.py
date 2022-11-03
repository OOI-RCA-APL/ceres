from __future__ import annotations

import inspect
import json
from dataclasses import is_dataclass
from datetime import datetime, timezone
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Iterable,
    TypeVar,
    cast,
    overload,
)

import pydantic
from pydantic import ConfigDict, Field, parse_obj_as
from pydantic.fields import FieldInfo
from pydantic.json import pydantic_encoder
from typing_extensions import dataclass_transform

T = TypeVar("T")


def utc() -> datetime:
    return datetime.now(timezone.utc)


async def awaitify(value: Awaitable[T] | T) -> T:
    if inspect.isawaitable(value):
        return cast(T, await value)

    return cast(T, value)


def hydrate(type: type[T], obj: Any) -> T:
    return parse_obj_as(type, obj)


def jsonify(obj: object, *, indent: int | str | None = None, **kwargs: Any) -> str:
    return json.dumps(
        obj,
        default=pydantic_encoder,
        indent=indent,
        **kwargs,
    )


def simplify(obj: Any) -> Any:
    return json.loads(jsonify(obj))


_VDC_FIELD_SPECIFIERS: tuple[Callable[..., Any], type[FieldInfo]] = (Field, FieldInfo)

if TYPE_CHECKING:

    @dataclass_transform(kw_only_default=True, field_specifiers=_VDC_FIELD_SPECIFIERS)
    @overload
    def vdc(
        *,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
        config: ConfigDict | type[object] | None = None,
        validate_on_init: bool | None = None,
        kw_only: bool = True,
    ) -> Callable[[type], type]:
        ...

    @dataclass_transform(kw_only_default=True, field_specifiers=_VDC_FIELD_SPECIFIERS)
    @overload
    def vdc(
        cls: type[T],
        *,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
        config: ConfigDict | type[object] | None = None,
        validate_on_init: bool | None = None,
        kw_only: bool = True,
    ) -> type[T]:
        ...


@dataclass_transform(kw_only_default=True, field_descriptors=_VDC_FIELD_SPECIFIERS)
def vdc(
    cls: type[T] | None = None,
    *,
    init: bool = True,
    repr: bool = True,
    eq: bool = True,
    order: bool = False,
    unsafe_hash: bool = False,
    frozen: bool = False,
    config: ConfigDict | type[object] | None = None,
    validate_on_init: bool | None = None,
    kw_only: bool = True,
) -> Callable[[type[T]], type[T]] | type:
    return pydantic.dataclasses.dataclass(
        cls,  # type: ignore
        init=init,
        repr=repr,
        eq=eq,
        order=order,
        unsafe_hash=unsafe_hash,
        frozen=frozen,
        config=config,
        validate_on_init=validate_on_init,
        kw_only=kw_only,
    )


class ValidateByType:
    @classmethod
    def __get_validators__(cls) -> Iterable[Any]:
        if hasattr(super(), "__get_validators__"):
            yield from super().__get_validators__()  # type: ignore

        def validate_type(value: Any) -> Any:
            if not isinstance(value, cls):
                raise ValueError(f"must be an instance of {cls}")
            return value

        yield validate_type


def is_pydantic_dataclass(obj: object) -> bool:
    return is_dataclass(obj) and hasattr(obj, "__pydantic_model__")
