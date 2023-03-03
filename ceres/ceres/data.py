import json
import re
from abc import ABC
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, cast

import pydantic
import pydantic.generics
from pydantic import (
    BaseConfig,
    BaseModel,
    ConfigDict,
    ConstrainedStr,
    Extra,
    Field,
    parse_obj_as,
)
from pydantic.fields import FieldInfo
from pydantic.json import pydantic_encoder
from typing_extensions import dataclass_transform

from .internal.utilities import PydanticDataclassLike, decode_td, dictify, is_pydantic_dataclass


def jsonify(obj: object, **kwargs: Any) -> str:
    default = kwargs.get("default")

    return json.dumps(
        obj,
        default=default if default is not None else pydantic_encoder,
        **kwargs,
    )


def simplify(obj: object) -> Any:
    return json.loads(jsonify(obj))


class DataObject(BaseModel, ABC):
    class Config(BaseConfig):
        arbitrary_types_allowed = True
        allow_population_by_field_name = True
        orm_mode = True
        validate_assignment = True
        extra = Extra.forbid

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
        allow_population_by_field_name=True,
        orm_mode=True,
        validate_assignment=True,
        extra=Extra.forbid,
    )
)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class ValidatedDataclass(ABC, PydanticDataclassLike):  # type: ignore
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


NAME_REGEX = re.compile(r"^[a-zA-Z_\-][a-zA-Z0-9_\-]*$")


class _Name(ConstrainedStr):
    regex = NAME_REGEX


class _DateTime(datetime):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> datetime | None:
        if value is None:
            return None

        timestamp = parse_obj_as(datetime, value)
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)

        return timestamp.astimezone(timezone.utc)


class _TimeDelta(timedelta):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> timedelta | None:
        if value is None:
            return None

        return decode_td(value)


class _PositiveTimeDelta(_TimeDelta):
    @classmethod
    def validate(cls, value: Any) -> timedelta | None:
        duration = super().validate(value)
        if duration is None:
            return None

        if duration <= timedelta():
            raise ValueError("must be greater than zero")

        return duration


class _NonNegativeTimeDelta(_TimeDelta):
    @classmethod
    def validate(cls, value: Any) -> timedelta | None:
        duration = super().validate(value)
        if duration is None:
            return None

        if duration < timedelta():
            raise ValueError("must be greater than or equal to zero")

        return duration


if TYPE_CHECKING:
    Name = str
    DateTime = datetime
    TimeDelta = timedelta
    PositiveTimeDelta = timedelta
    NonNegativeTimeDelta = timedelta
else:
    Name = _Name
    Name.__name__ = "Name"
    DateTime = _DateTime
    DateTime.__name__ = "DateTime"
    TimeDelta = _TimeDelta
    TimeDelta.__name__ = "TimeDelta"
    PositiveTimeDelta = _PositiveTimeDelta
    PositiveTimeDelta.__name__ = "PositiveTimeDelta"
    NonNegativeTimeDelta = _NonNegativeTimeDelta
    NonNegativeTimeDelta.__name__ = "NonNegativeTimeDelta"
