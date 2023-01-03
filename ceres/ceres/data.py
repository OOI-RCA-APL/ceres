import json
from abc import ABC
from types import MappingProxyType
from typing import Any, Callable, cast

import pydantic
import pydantic.generics
from pydantic import BaseConfig, ConfigDict, Field
from pydantic.fields import FieldInfo
from pydantic.fields import FieldInfo as FieldInfo
from pydantic.generics import GenericModel
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


class DataObject(GenericModel, ABC):
    class Config(BaseConfig):
        arbitrary_types_allowed = True
        orm_mode = True
        validate_assignment = True

    def __str__(self) -> str:
        return super().__repr__()


class ImmutableDataObject(DataObject, ABC):
    class Config(DataObject.Config):
        frozen = True


VALIDATED_DATACLASS_FIELD_SPECIFIERS: tuple[Callable[..., Any], type[FieldInfo]] = (
    Field,
    FieldInfo,
)
VALIDATED_DATACLASS_DEFAULT_CONFIG = MappingProxyType(
    ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
    )
)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class ValidatedDataclass(ABC):
    def __init_subclass__(
        cls,
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
    ) -> None:
        super().__init_subclass__()
        inherited_config = ConfigDict()

        for base in reversed(cls.__bases__):
            if is_pydantic_dataclass(base):
                inherited_config.update(
                    cast(ConfigDict, dictify(base.__pydantic_model__.__config__))
                )

        config = ConfigDict(
            **{
                **VALIDATED_DATACLASS_DEFAULT_CONFIG,
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
