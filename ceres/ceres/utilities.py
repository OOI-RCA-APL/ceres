from __future__ import annotations

import dataclasses
import inspect
import json
from abc import ABCMeta
from datetime import datetime, timezone
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Iterable,
    Mapping,
    Protocol,
    TypeGuard,
    TypeVar,
    cast,
    overload,
    runtime_checkable,
)

import pydantic
from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo
from pydantic.json import pydantic_encoder
from typing_extensions import dataclass_transform

_T = TypeVar("_T")


def utc() -> datetime:
    return datetime.now(timezone.utc)


async def awaitify(value: Awaitable[_T] | _T) -> _T:
    if inspect.isawaitable(value):
        return cast(_T, await value)

    return cast(_T, value)


def jsonify(obj: object, *, indent: int | str | None = None, **kwargs: Any) -> str:
    return json.dumps(
        obj,
        default=pydantic_encoder,
        indent=indent,
        **kwargs,
    )


def simplify(obj: object) -> Any:
    return json.loads(jsonify(obj))


def dictify(obj: object) -> dict[str, Any]:
    def includes(key: str) -> bool:
        return not key.startswith("__")

    try:
        if isinstance(obj, Mapping):
            return dict(obj)
        if is_dataclass(obj):
            return dataclasses.asdict(obj)
        if isinstance(obj, BaseModel):
            return obj.dict()
        if isinstance(obj, type):
            return {key: getattr(obj, key) for key in dir(obj) if includes(key)}
        if hasattr(obj, "__slots__"):
            return {
                name: getattr(obj, name) for name in obj.__slots__ if includes(name)  # type: ignore
            }
        return {key: value for key, value in obj.__dict__.items() if not includes(key)}
    except Exception:
        raise ValueError("object cannot be dictified")


VALIDATED_DATACLASS_FIELD_SPECIFIERS: tuple[Callable[..., Any], type[FieldInfo]] = (
    Field,
    FieldInfo,
)

if TYPE_CHECKING:

    @dataclass_transform(
        kw_only_default=True,
        field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    )
    @overload
    def vdc(
        *,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
        config: ConfigDict | None = None,
        validate_on_init: bool | None = None,
        kw_only: bool = True,
    ) -> Callable[[type], type]:
        ...

    @dataclass_transform(
        kw_only_default=True,
        field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    )
    @overload
    def vdc(
        cls: type[_T],
        *,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
        config: ConfigDict | None = None,
        validate_on_init: bool | None = None,
        kw_only: bool = True,
    ) -> type[_T]:
        ...


@dataclass_transform(
    kw_only_default=True,
    field_descriptors=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
def vdc(
    cls: type[_T] | None = None,
    *,
    init: bool = True,
    repr: bool = True,
    eq: bool = True,
    order: bool = False,
    unsafe_hash: bool = False,
    frozen: bool = False,
    config: ConfigDict | None = None,
    validate_on_init: bool | None = None,
    kw_only: bool = True,
) -> Callable[[type[_T]], type[_T]] | type:
    config_defaults = ConfigDict(
        arbitrary_types_allowed=True,
    )

    if config:
        config = ConfigDict(**{**config_defaults, **config})
    else:
        config = config_defaults

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


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class ValidatedDataclassMeta(ABCMeta):
    def __new__(
        metacls,  # type: ignore
        name: str,
        bases: tuple[type[Any], ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type[Any]:
        cls = super().__new__(metacls, name, bases, namespace)
        dataclass_params: dict[str, Any] = {}
        pydantic_config: dict[str, Any] = {}

        for base in reversed(bases):
            if not is_dataclass(base):
                continue

            dataclass_params.update(dictify(base.__dataclass_params__))

            if is_validated_dataclass(base):
                pydantic_config.update(dictify(base.__pydantic_model__.__config__))

        cls = vdc(cls, **{**dataclass_params, **kwargs})  # type: ignore
        return cls


@runtime_checkable
class DataclassLike(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]
    __dataclass_params__: ClassVar[Any]
    __post_init__: ClassVar[Callable[..., None]]


@runtime_checkable
class ValidatedDataclassLike(DataclassLike, Protocol):
    __pydantic_run_validation__: ClassVar[bool]
    __post_init_post_parse__: ClassVar[Callable[..., None]]
    __pydantic_initialised__: ClassVar[bool]
    __pydantic_model__: ClassVar[type[BaseModel]]
    __pydantic_validate_values__: ClassVar[Callable[[DataclassLike], None]]
    __pydantic_has_field_info_default__: ClassVar[bool]


def is_dataclass(obj: object) -> TypeGuard[DataclassLike]:
    return dataclasses.is_dataclass(obj)


def is_validated_dataclass(obj: object) -> TypeGuard[ValidatedDataclassLike]:
    return dataclasses.is_dataclass(obj) and hasattr(obj, "__pydantic_model__")
