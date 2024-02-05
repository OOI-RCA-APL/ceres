import json
from abc import ABC
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Annotated, Any, Callable, Literal, NewType, cast

import pydantic
import pydantic.generics
import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)
from pydantic import EmailStr as _BaseEmailStr
from pydantic.fields import FieldInfo
from pydantic_extra_types.color import Color as Color
from typing_extensions import dataclass_transform

from ceres.internal.utilities import (
    NAME_PATTERN,
    PydanticDataclassLike,
    decode_td,
    get_type_adapter,
    is_pydantic_dataclass_type,
)


def jsonify(obj: object, **kwargs: Any) -> str:
    return get_type_adapter(type(obj)).dump_json(obj, **kwargs).decode()


def simplify(obj: object) -> Any:
    return json.loads(jsonify(obj))


def yamlify(obj: object, **kwargs: Any) -> str:
    return yaml.safe_dump(simplify(obj), **kwargs)


Name = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
NonBlankStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]


def __validate_date(value: date | None) -> date | None:
    return value


Date = Annotated[date, AfterValidator(__validate_date)]


def __validate_datetime(value: object) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        instance = value
    else:
        instance = get_type_adapter(datetime | date).validate_python(value)
        if not isinstance(instance, datetime):
            return datetime(
                year=instance.year,
                month=instance.month,
                day=instance.day,
                tzinfo=timezone.utc,
            )

    if instance.tzinfo is None:
        return instance.replace(tzinfo=timezone.utc)

    return instance.astimezone(timezone.utc)


DateTime = Annotated[datetime, AfterValidator(__validate_datetime)]


def __validate_timedelta(value: Any) -> timedelta | None:
    if value is None:
        return None

    return decode_td(value)


TimeDelta = Annotated[timedelta, BeforeValidator(__validate_timedelta)]

__ZERO_TIMEDELTA = timedelta()


def __validate_positive_timedelta(value: object) -> timedelta | None:
    delta = __validate_timedelta(value)
    if delta is None:
        return None

    assert delta > __ZERO_TIMEDELTA, "must be greater than zero"
    return delta


PositiveTimeDelta = Annotated[timedelta, BeforeValidator(__validate_positive_timedelta)]


def __validate_non_negative_timedelta(value: object) -> timedelta | None:
    delta = __validate_timedelta(value)
    if delta is None:
        return None

    assert delta >= __ZERO_TIMEDELTA, "must be greater than or equal to zero"
    return delta


NonNegativeTimeDelta = Annotated[timedelta, BeforeValidator(__validate_non_negative_timedelta)]


def __pre_validate_json_object(value: object) -> object:
    if isinstance(value, str | bytes):
        return json.loads(value)

    return value


def __pre_validate_json_array(value: object) -> object:
    if isinstance(value, str | bytes):
        return json.loads(value)

    return value


JSON = None | bool | int | float | str | dict[str, Any] | list[Any]
JSONDict = Annotated[dict[str, Any], BeforeValidator(__pre_validate_json_object)]
JSONList = Annotated[list[Any], BeforeValidator(__pre_validate_json_array)]


class DataObject(BaseModel, ABC):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    def __str__(self) -> str:
        return super().__repr__()


class ImmutableDataObject(DataObject, ABC):
    model_config = ConfigDict(frozen=True)


VALIDATED_DATACLASS_FIELD_SPECIFIERS: tuple[Callable[..., Any], type[FieldInfo]] = (
    Field,
    FieldInfo,
)
VALIDATED_DATACLASS_DEFAULT_CONFIG = cast(
    ConfigDict, MappingProxyType(ConfigDict(**DataObject.model_config))
)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class ValidatedDataclass(ABC, PydanticDataclassLike):  # type: ignore
    def __init_subclass__(
        cls,
        *,
        init: Literal[False] = False,
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
            if is_pydantic_dataclass_type(base):
                inherited_config.update(base.__pydantic_config__)

        config = ConfigDict(
            **{
                **VALIDATED_DATACLASS_DEFAULT_CONFIG,
                **inherited_config,
                **ConfigDict(title=cls.__qualname__),
                **(config or ConfigDict()),
            }
        )

        pydantic.dataclasses.dataclass(
            init=init,
            repr=repr,
            eq=eq,
            order=order,
            unsafe_hash=unsafe_hash,
            frozen=frozen,
            config=config,
            validate_on_init=validate_on_init,
            kw_only=kw_only,
        )(cls)


UsernameStr = Annotated[
    str,
    StringConstraints(
        pattern=r"[a-zA-Z\-_]{1,64}",
        min_length=1,
        max_length=64,
    ),
]

PasswordStr = Annotated[str, StringConstraints(min_length=1, max_length=256)]
EmailStr = _BaseEmailStr

_BCRYPT_HASH_PATTERN = r"^\$2[ayb]\$.{56}$"

BCryptHash = NewType(
    "BCryptHash",
    Annotated[str, StringConstraints(pattern=_BCRYPT_HASH_PATTERN)],
)

PasswordHash = BCryptHash
