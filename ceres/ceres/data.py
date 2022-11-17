from __future__ import annotations

import dataclasses
import json
from abc import ABC
from types import MappingProxyType
from typing import Any, Callable, ClassVar, cast

import pydantic
from pydantic import ConfigDict, Field
from pydantic.fields import FieldInfo
from pydantic.fields import FieldInfo as FieldInfo
from pydantic.json import pydantic_encoder
from typing_extensions import dataclass_transform

from .internal.utilities import dictify, is_pydantic_dataclass


def jsonify(obj: object, **kwargs: Any) -> str:
    default = kwargs.get("default")

    return json.dumps(
        obj,
        default=default if default is not None else pydantic_encoder,
        **kwargs,
    )


def simplify(obj: object) -> Any:
    return json.loads(jsonify(obj))


DATA_OBJECT_FIELD_SPECIFIERS: tuple[Callable[..., Any], type[FieldInfo]] = (Field, FieldInfo)
DATA_OBJECT_DEFAULT_CONFIG = MappingProxyType(
    ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
    )
)


@dataclasses.dataclass(kw_only=True, frozen=True)
class _DataObjectParams:
    immutable: bool = False


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=DATA_OBJECT_FIELD_SPECIFIERS,
)
class DataObject(ABC):
    __data_object_params__: ClassVar[_DataObjectParams] = _DataObjectParams()

    def __init_subclass__(
        cls,
        *,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        immutable: bool = False,
        frozen: bool = False,
        config: ConfigDict | None = None,
        validate_on_init: bool | None = None,
        kw_only: bool = True,
    ) -> None:
        cls.__data_object_params__ = dataclasses.replace(
            cls.__data_object_params__,
            immutable=immutable or cls.__data_object_params__.immutable,
        )

        if cls.__data_object_params__.immutable:
            frozen = True

        inherited_config = ConfigDict()

        for base in reversed(cls.__bases__):
            if is_pydantic_dataclass(base):
                inherited_config.update(
                    cast(ConfigDict, dictify(base.__pydantic_model__.__config__))
                )

        config = ConfigDict(
            **{
                **DATA_OBJECT_DEFAULT_CONFIG,
                **inherited_config,
                **ConfigDict(
                    title=cls.__qualname__,
                ),
                **(config or ConfigDict()),
            }
        )

        pydantic.dataclasses.dataclass(
            cls,
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
