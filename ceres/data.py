import json
from abc import ABC
from datetime import date, datetime, timedelta, timezone
from json import JSONDecodeError
from typing import Annotated, Any, Literal, NewType, Sized, TypeVar

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
from yaml import YAMLError

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


def __pre_validate_from_json(value: object) -> object:
    if isinstance(value, str | bytes):
        try:
            return json.loads(value)
        except JSONDecodeError as error:
            raise ValueError(f"invalid JSON: {error}")

    return value


def __pre_validate_from_yaml(value: object) -> object:
    if isinstance(value, str | bytes):
        try:
            return yaml.safe_load(value)
        except YAMLError as error:
            raise ValueError(f"invalid YAML: {error}")

    return value


_T = TypeVar("_T")

FromJSON = Annotated[_T, BeforeValidator(__pre_validate_from_json)]
FromYAML = Annotated[_T, BeforeValidator(__pre_validate_from_yaml)]


def __validate_non_empty(value: object) -> object:
    if isinstance(value, Sized):
        assert len(value) > 0, "cannot not be empty"

    return value


NonEmpty = Annotated[_T, AfterValidator(__validate_non_empty)]

JSON = None | bool | int | float | str | dict[str, Any] | list[Any]
JSONDict = FromJSON[dict[str, Any]]
JSONList = FromJSON[list[Any]]


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


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(Field, FieldInfo),
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
                **DataObject.model_config,
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


__USERNAME_PATTERN = r"[a-zA-Z\-_]+"

UsernameStr = Annotated[
    str,
    StringConstraints(
        pattern=__USERNAME_PATTERN,
        min_length=1,
        max_length=64,
    ),
]


def __validate_password_str(value: str) -> str:
    bytes = len(value.encode())
    if bytes > 72:
        raise ValueError("password cannot exceed 72 bytes")

    return value


PasswordStr = Annotated[
    str,
    StringConstraints(min_length=1, max_length=32),
    AfterValidator(__validate_password_str),
]

EmailStr = _BaseEmailStr

__BCRYPT_HASH_PATTERN = r"^\$2[ayb]\$.{56}$"

BCryptHash = NewType(
    "BCryptHash",
    Annotated[str, StringConstraints(pattern=__BCRYPT_HASH_PATTERN)],
)

__ARGON2_HASH_PATTERN = r"^\$argon2(?:(?:id)|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/$]+$"

Argon2Hash = NewType(
    "Argon2Hash",
    Annotated[str, StringConstraints(pattern=__ARGON2_HASH_PATTERN)],
)

PasswordHash = BCryptHash | Argon2Hash
