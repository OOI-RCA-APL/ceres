from __future__ import annotations

import json
from abc import ABC
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum as BaseStrEnum
from json import JSONDecodeError
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    ClassVar,
    Literal,
    NewType,
    Sized,
    TypedDict,
    TypeVar,
    Unpack,
    dataclass_transform,
    override,
)

import pydantic
import pydantic.generics
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
)
from pydantic import EmailStr as _BaseEmailStr
from pydantic.fields import FieldInfo
from pydantic.main import IncEx
from pydantic_core import CoreSchema, SchemaSerializer, SchemaValidator
from pydantic_extra_types.color import Color as Color

from ceres._internal import util
from ceres._internal.util import NAME_PATTERN, PydanticDataclassLike


class SimplifyArgs(TypedDict, total=False):
    include: IncEx | None
    exclude: IncEx | None
    by_alias: bool
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool


class SerializeArgs(SimplifyArgs, total=False):
    indent: int | None


__ANY_ADAPTOR = TypeAdapter(Any) if not TYPE_CHECKING else TypeAdapter(object)


def simplify(obj: object, **kwargs: Unpack[SimplifyArgs]) -> Any:
    kwargs["round_trip"] = True  # type: ignore
    return __ANY_ADAPTOR.dump_python(obj, **kwargs)


def jsonify(obj: object, **kwargs: Unpack[SerializeArgs]) -> str:
    return __ANY_ADAPTOR.dump_json(obj, **kwargs).decode()


def yamlify(obj: object, **kwargs: Unpack[SerializeArgs]) -> str:
    import yaml

    return yaml.safe_dump(simplify(obj, **kwargs), indent=kwargs.get("indent", None))


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
        instance: datetime | date = util.get_type_adapter(datetime | date).validate_python(value)  # type: ignore
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

    return util.decode_td(value)


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
    import yaml
    from yaml import YAMLError

    if isinstance(value, str | bytes):
        try:
            return yaml.safe_load(value)
        except YAMLError as error:
            raise ValueError(f"invalid YAML: {error}")

    return value


_T = TypeVar("_T")

FromJSON = Annotated[_T, BeforeValidator(__pre_validate_from_json)]
FromYAML = Annotated[_T, BeforeValidator(__pre_validate_from_yaml)]


def __validate_jsonable(value: object) -> object:
    try:
        jsonify(value)
    except Exception as error:
        raise ValueError(f"not serializable to JSON: {error}")

    return value


def __validate_yamlable(value: object) -> object:
    try:
        yamlify(value)
    except Exception as error:
        raise ValueError(f"not serializable to YAML: {error}")

    return value


JSONWriteable = Annotated[_T, AfterValidator(__validate_jsonable)]
JSONDict = JSONWriteable[FromJSON[dict[str, Any]]]
JSONList = JSONWriteable[FromJSON[list[Any]]]
JSONValue = None | bool | int | float | str | JSONDict | JSONList


def __validate_non_empty(value: object) -> object:
    if isinstance(value, Sized):
        assert len(value) > 0, "cannot not be empty"

    return value


NonEmpty = Annotated[_T, AfterValidator(__validate_non_empty)]


class DataObject(BaseModel, ABC):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    @override
    def __str__(self) -> str:
        return super().__repr__()


class ImmutableDataObject(DataObject, ABC):
    model_config = ConfigDict(frozen=True)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(Field, FieldInfo),
)
class ValidatedDataclass(ABC, PydanticDataclassLike):
    if TYPE_CHECKING:
        __dataclass_fields__: ClassVar[dict[str, Any]]
        __dataclass_params__: ClassVar[Any]
        __post_init__: ClassVar[Callable[..., None]]

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        __pydantic_config__: ClassVar[ConfigDict]
        __pydantic_complete__: ClassVar[bool]
        __pydantic_core_schema__: ClassVar[CoreSchema]
        __pydantic_decorators__: ClassVar[Any]
        __pydantic_fields__: ClassVar[dict[str, FieldInfo]]
        __pydantic_serializer__: ClassVar[SchemaSerializer]
        __pydantic_validator__: ClassVar[SchemaValidator]

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
            if util.is_pydantic_dataclass_type(base):
                inherited_config.update(base.__pydantic_config__)

        config = ConfigDict(
            **{  # type: ignore
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

if TYPE_CHECKING:
    util.blackhole(__BCRYPT_HASH_PATTERN)

BCryptHash = NewType(
    "BCryptHash",
    str if TYPE_CHECKING else Annotated[str, StringConstraints(pattern=__BCRYPT_HASH_PATTERN)],
)

__ARGON2_HASH_PATTERN = r"^\$argon2(?:(?:id)|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/$]+$"

if TYPE_CHECKING:
    util.blackhole(__ARGON2_HASH_PATTERN)

Argon2Hash = NewType(
    "Argon2Hash",
    str if TYPE_CHECKING else Annotated[str, StringConstraints(pattern=__ARGON2_HASH_PATTERN)],
)

PasswordHash = BCryptHash | Argon2Hash


class StrEnum(BaseStrEnum):
    @staticmethod
    @override
    def _generate_next_value_(name: str, *args: Any, **kwargs: Any) -> str:
        return name.lower().replace("_", "-")

    @override
    def __str__(self) -> str:
        return self.value


_priority_cache: dict[tuple[type[PriorityStrEnum], str], int] = {}


class PriorityStrEnum(StrEnum):
    @property
    def priority(self) -> Any:
        key = (type(self), self)
        priority = _priority_cache.get(key)
        if priority is None:
            priority = tuple(type(self)).index(self)
            _priority_cache[key] = priority

        return priority

    @override
    def __lt__(self, __x: str | None) -> bool:
        if __x is None:
            return False

        if isinstance(__x, type(self)):
            return self.priority < __x.priority

        return super().__lt__(__x)

    @override
    def __le__(self, __x: str | None) -> bool:
        if __x is None:
            return False

        if isinstance(__x, type(self)):
            return self.priority <= __x.priority

        return super().__le__(__x)

    @override
    def __gt__(self, __x: str | None) -> bool:
        if __x is None:
            return True

        if isinstance(__x, type(self)):
            return self.priority > __x.priority

        return super().__gt__(__x)

    @override
    def __ge__(self, __x: str | None) -> bool:
        if __x is None:
            return True

        if isinstance(__x, type(self)):
            return self.priority >= __x.priority

        return super().__ge__(__x)
