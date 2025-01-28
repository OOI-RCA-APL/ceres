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
    Sequence,
    Sized,
    TypeAlias,
    TypedDict,
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
)
from pydantic import EmailStr as _BaseEmailStr
from pydantic.fields import FieldInfo
from pydantic.functional_serializers import PlainSerializer
from pydantic.main import IncEx
from pydantic_core import CoreSchema, SchemaSerializer, SchemaValidator
from pydantic_extra_types.color import Color as Color
from typing_extensions import TypeVar

from ceres._internal import util
from ceres._internal.util import NAME_PATTERN, PydanticDataclassLike, get_type_adapter


class SimplifyArgs(TypedDict, total=False):
    include: IncEx | None
    exclude: IncEx | None
    by_alias: bool
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool


class SerializeArgs(SimplifyArgs, total=False):
    indent: int | None


def simplify(obj: object, **kwargs: Unpack[SimplifyArgs]) -> Any:
    return json.loads(jsonify(obj, **kwargs))


def jsonify(obj: object, **kwargs: Unpack[SerializeArgs]) -> str:
    return get_type_adapter(type(obj)).dump_json(obj, **kwargs).decode()


def yamlify(obj: object, **kwargs: Unpack[SerializeArgs]) -> str:
    import yaml

    return yaml.safe_dump(simplify(obj, **kwargs), indent=kwargs.get("indent", None))


Name: TypeAlias = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
NonEmptyStr: TypeAlias = Annotated[str, StringConstraints(min_length=1)]
NonBlankStr: TypeAlias = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]


def __validate_date(value: date | None) -> date | None:
    return value


Date: TypeAlias = Annotated[date, AfterValidator(__validate_date)]


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


DateTime: TypeAlias = Annotated[datetime, AfterValidator(__validate_datetime)]


def __validate_timedelta(value: Any) -> timedelta | None:
    if value is None:
        return None

    return util.decode_td(value)


TimeDelta: TypeAlias = Annotated[timedelta, BeforeValidator(__validate_timedelta)]

__ZERO_TIMEDELTA = timedelta()


def __validate_positive_timedelta(value: object) -> timedelta | None:
    delta = __validate_timedelta(value)
    if delta is None:
        return None

    assert delta > __ZERO_TIMEDELTA, "must be greater than zero"
    return delta


PositiveTimeDelta: TypeAlias = Annotated[timedelta, BeforeValidator(__validate_positive_timedelta)]


def __validate_non_negative_timedelta(value: object) -> timedelta | None:
    delta = __validate_timedelta(value)
    if delta is None:
        return None

    assert delta >= __ZERO_TIMEDELTA, "must be greater than or equal to zero"
    return delta


NonNegativeTimeDelta: TypeAlias = Annotated[
    timedelta, BeforeValidator(__validate_non_negative_timedelta)
]


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

FromJson: TypeAlias = Annotated[_T, BeforeValidator(__pre_validate_from_json)]
FromYaml: TypeAlias = Annotated[_T, BeforeValidator(__pre_validate_from_yaml)]


def __validate_number(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)

    return value


def __serialize_number(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)

    return value


Number: TypeAlias = Annotated[
    int | float,
    Field(union_mode="left_to_right"),
    BeforeValidator(__validate_number),
    PlainSerializer(__serialize_number),
]

type JSONValue = None | bool | Number | str | JSONList | JSONDict
JSONDict: TypeAlias = dict[str, JSONValue]
JSONList: TypeAlias = list[JSONValue]


def __validate_jsonable(value: object) -> object:
    try:
        jsonify(value)
    except Exception as error:
        raise ValueError(f"not serializable to JSON: {error}")

    return value


_TAny = TypeVar("_TAny", default=Any)
JSONSerializable: TypeAlias = Annotated[_TAny, AfterValidator(__validate_jsonable)]

_TKey = TypeVar("_TKey", default=str)
_TValue = TypeVar("_TValue", default=Any)
JSONSerializableDict: TypeAlias = JSONSerializable[dict[str, _TValue]]
JSONSerializableList: TypeAlias = JSONSerializable[list[_TValue]]

if TYPE_CHECKING:
    MaybeSequence: TypeAlias = _T | Sequence[_T]
else:
    MaybeSequence: TypeAlias = _T | list[_T]


def __validate_non_empty(value: object) -> object:
    if isinstance(value, Sized):
        assert len(value) > 0, "cannot not be empty"

    return value


NonEmpty: TypeAlias = Annotated[_T, AfterValidator(__validate_non_empty)]


class DataObject(BaseModel, ABC):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        use_attribute_docstrings=True,
    )

    @override
    def __str__(self) -> str:
        return super().__repr__()


class ImmutableDataObject(DataObject):
    model_config = ConfigDict(frozen=True)


class DeferBuild(BaseModel, ABC):
    model_config = ConfigDict(defer_build=True)


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

UsernameStr: TypeAlias = Annotated[
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


PasswordStr: TypeAlias = Annotated[
    str,
    StringConstraints(min_length=1, max_length=32),
    AfterValidator(__validate_password_str),
]

EmailStr: TypeAlias = _BaseEmailStr

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

PasswordHash: TypeAlias = BCryptHash | Argon2Hash


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
