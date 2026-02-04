from __future__ import annotations

import dataclasses
from abc import ABC
from collections.abc import Callable, Mapping, Sequence, Sized
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum as BaseStrEnum
from re import RegexFlag
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Literal,
    NewType,
    Protocol,
    Self,
    TypeAlias,
    TypedDict,
    Unpack,
    cast,
    dataclass_transform,
    override,
    runtime_checkable,
)
from uuid import UUID

import pydantic
from pydantic import (
    AfterValidator,
    AliasGenerator,
    AliasPath,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    PlainSerializer,
    StringConstraints,
    model_validator,
)
from pydantic.aliases import AliasChoices
from pydantic.fields import FieldInfo
from pydantic_core import ArgsKwargs, PydanticUndefined
from pydantic_extra_types.color import Color as Color
from pydantic_settings import NoDecode
from typing_extensions import TypeVar

from ceres._internal import util
from ceres._internal.util import NAME_PATTERN, PydanticDataclassLike, get_type_adapter

if TYPE_CHECKING:
    from inspect import Signature

    from pydantic.main import IncEx
    from pydantic_core import CoreSchema, SchemaSerializer, SchemaValidator


class SimplifyKwargs(TypedDict, total=False):
    include: IncEx | None
    exclude: IncEx | None
    by_alias: bool
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool


class SerializeKwargs(SimplifyKwargs, total=False):
    indent: int | None


def simplify(obj: object, **kwargs: Unpack[SimplifyKwargs]) -> Any:
    import json

    return json.loads(jsonify(obj, **kwargs))


def jsonify(obj: object, **kwargs: Unpack[SerializeKwargs]) -> str:
    return get_type_adapter(type(obj)).dump_json(obj, **kwargs).decode()


def yamlify(obj: object, **kwargs: Unpack[SerializeKwargs]) -> str:
    import yaml

    return yaml.safe_dump(simplify(obj, **kwargs), indent=kwargs.get("indent", None))


def dictify(obj: object) -> dict[str, Any]:
    def includes(key: str) -> bool:
        return not key.startswith("__")

    try:
        if util.is_mapping(obj):
            return dict(obj)
        if util.is_dataclass_instance(obj):
            return dataclasses.asdict(obj)
        if isinstance(obj, BaseModel):
            return {key: getattr(obj, key) for key in type(obj).model_fields}
        if isinstance(obj, type):
            return {key: getattr(obj, key) for key in dir(obj) if includes(key)}

        output = {}

        __slots__: tuple[str, ...] | None = getattr(obj, "__slots__", None)
        if __slots__:
            output.update({name: getattr(obj, name) for name in __slots__ if includes(name)})

        __dict__: dict[str, Any] = getattr(obj, "__dict__", {})
        if __dict__:
            output.update({key: value for key, value in __dict__.items() if includes(key)})

        return output
    except Exception:
        raise ValueError(f"`{type(obj)}` cannot be converted to a dictionary.")


BytesLike: TypeAlias = bytes | bytearray

if TYPE_CHECKING:
    from typing import SupportsBytes

    ToBytes: TypeAlias = bytes | bytearray | memoryview | str | SupportsBytes
else:
    ToBytes: TypeAlias = bytes | bytearray | str


def to_bytes(
    data: ToBytes,
    /,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> bytes:
    if isinstance(data, str):
        return bytes(data, encoding, errors)

    return bytes(data)


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
                tzinfo=UTC,
            )

    if instance.tzinfo is None:
        return instance.replace(tzinfo=UTC)

    return instance.astimezone(UTC)


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
    timedelta,
    BeforeValidator(__validate_non_negative_timedelta),
]


def uuid4() -> UUID:
    """Generate a version 4 UUID."""
    try:
        from uuid_utils import uuid4

        return UUID(int=uuid4().int)
    except ImportError:
        from uuid import uuid4

        return uuid4()


def uuid7(
    timestamp: int | None = None,
    nanoseconds: int | None = None,
) -> UUID:
    """Generate a version 7 UUID using a time value and random bytes."""
    from uuid_utils import uuid7

    return UUID(int=uuid7(timestamp, nanoseconds).int)


def __pre_validate_from_json(value: object) -> object:
    if isinstance(value, str | bytes):
        import json

        try:
            return json.loads(value)
        except Exception as error:
            raise ValueError(f"invalid JSON: {error}")

    return value


def __pre_validate_from_yaml(value: object) -> object:
    if isinstance(value, str | bytes):
        import json

        try:
            return json.loads(value)
        except Exception:
            pass

        import yaml

        try:
            return yaml.safe_load(value)
        except Exception as error:
            raise ValueError(f"invalid YAML: {error}")

    return value


_T = TypeVar("_T")

FromJSON: TypeAlias = Annotated[_T, BeforeValidator(__pre_validate_from_json), NoDecode]
FromYAML: TypeAlias = Annotated[_T, BeforeValidator(__pre_validate_from_yaml), NoDecode]


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


def __generate_validation_aliases(field: str) -> str | AliasChoices:
    if "_" not in field:
        return field

    return AliasChoices(field, field.replace("_", "-"))


_DATA_OBJECT_ALIAS_GENERATOR = AliasGenerator(
    validation_alias=__generate_validation_aliases,
)


class DataObject(BaseModel, ABC):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        use_attribute_docstrings=True,
        alias_generator=_DATA_OBJECT_ALIAS_GENERATOR,
    )

    @override
    def __setattr__(self, name: str, value: Any, /) -> None:
        super().__setattr__(name, value)
        self.model_fields_set.add(name)

    @override
    def __repr__(self) -> str:
        fields = self.model_fields_set
        tokens: list[str] = [self.__class__.__name__, "("]
        for i, field in enumerate(fields):
            try:
                value = getattr(self, field)
            except Exception:
                continue

            if i < len(fields) - 1:
                tokens.append(f"{field}={value!r}, ")
            else:
                tokens.append(f"{field}={value!r}")

        tokens.append(")")
        return "".join(tokens)

    @override
    def __str__(self) -> str:
        return self.__repr__()


class ImmutableDataObject(DataObject):
    model_config = ConfigDict(frozen=True)


def _patch_dataclass_fields() -> None:
    try:
        _original_as_dataclass_field: Any = pydantic._internal._dataclasses.as_dataclass_field  # type: ignore
    except AttributeError:
        _original_as_dataclass_field = None

    if _original_as_dataclass_field is not None:

        def overridden_as_dataclass_field(pydantic_field: FieldInfo) -> dataclasses.Field[Any]:
            field = _original_as_dataclass_field(pydantic_field)
            if pydantic_field.kw_only is not None:
                field.kw_only = pydantic_field.kw_only

            return field

        pydantic._internal._dataclasses.as_dataclass_field = overridden_as_dataclass_field  # type: ignore


if TYPE_CHECKING:
    from ceres.component import ConnectionField
else:
    ConnectionField = object

_patch_dataclass_fields()


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(
        Field,
        FieldInfo,
        dataclasses.field,
        dataclasses.Field,
        ConnectionField,
    ),
)
class ValidatedDataclass(ABC, PydanticDataclassLike):
    __slots__ = (
        "__weakref__",
        "__pydantic_fields_set__",
    )

    if TYPE_CHECKING:
        __pydantic_fields_set__: set[str]
        """
        Set of field names that were explicitly set during initialization. Used for equivalent
        set/unset functionality as with Pydantic's `BaseModel`.
        """

        # Class attributes and methods from `pydantic.dataclasses.dataclass`.
        __dataclass_fields__: ClassVar[dict[str, Any]]
        __dataclass_params__: ClassVar[Any]
        __post_init__: ClassVar[Callable[..., None]]

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        __signature__: ClassVar[Signature]
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
        init: Literal[True] = True,
        repr: Literal[True] = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
        config: ConfigDict | None = None,
        validate_on_init: bool | None = None,
        kw_only: bool = True,
        slots: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        inherited = ConfigDict()

        for base in reversed(cls.__bases__):
            if util.is_pydantic_dataclass_type(base):
                inherited.update(base.__pydantic_config__)

        config = ConfigDict(
            **{  # type: ignore
                **DataObject.model_config,
                **inherited,
                **ConfigDict(title=cls.__qualname__),
                **(config or ConfigDict()),
            }
        )

        pydantic.dataclasses.dataclass(
            eq=eq,
            order=order,
            unsafe_hash=unsafe_hash,
            frozen=frozen,
            config=config,
            validate_on_init=validate_on_init,
            kw_only=kw_only,
            slots=slots,
        )(cls)

    @model_validator(mode="wrap")
    @classmethod
    def _init__pydantic_fields_set__(
        cls,
        data: Any,
        handler: ModelWrapValidatorHandler[Self],
    ) -> ValidatedDataclass:
        if isinstance(data, Mapping | ArgsKwargs):
            __pydantic_fields_set__ = cls._compute_fields_set(data)
        else:
            __pydantic_fields_set__ = {*cls.__pydantic_fields__.keys()}

        instance = handler(data)
        if not hasattr(instance, "__pydantic_fields_set__"):
            instance.__pydantic_fields_set__ = __pydantic_fields_set__
        else:
            instance.__pydantic_fields_set__.update(instance.__pydantic_fields_set__)

        return instance

    @classmethod
    def _compute_fields_set(cls, values: Mapping[str, Any] | ArgsKwargs) -> set[str]:
        fields_set = set()

        if isinstance(values, ArgsKwargs):
            from inspect import Parameter

            # Handle positional arguments.
            count = len(values.args)
            for i, parameter in enumerate(cls.__signature__.parameters.values()):
                if i >= count:
                    break

                if (
                    parameter.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
                    and parameter.name in cls.__pydantic_fields__
                ):
                    fields_set.add(parameter.name)

            values = values.kwargs or {}

        # Taken from Pydantic's implementation.
        for name, field in cls.__pydantic_fields__.items():
            if field.alias is not None and field.alias in values:
                fields_set.add(name)

            if (name not in fields_set) and (field.validation_alias is not None):
                aliases: list[str | AliasPath] = (
                    field.validation_alias.choices
                    if isinstance(field.validation_alias, AliasChoices)
                    else [field.validation_alias]
                )

                for alias in aliases:
                    if isinstance(alias, str) and alias in values:
                        fields_set.add(name)
                        break

                    if isinstance(alias, AliasPath):
                        value = alias.search_dict_for_path(cast("dict[str, Any]", values))
                        if value is not PydanticUndefined:
                            fields_set.add(name)
                            break

            if name not in fields_set:
                if name in values:
                    fields_set.add(name)
                elif not field.is_required():
                    pass

        return fields_set

    @override
    def __setattr__(self, name: str, value: Any, /) -> None:
        super().__setattr__(name, value)
        if name in self.__pydantic_fields__:
            self.__pydantic_fields_set__.add(name)

    @override
    def __repr__(self) -> str:
        tokens: list[str] = [self.__class__.__name__, "("]
        for name in self.__pydantic_fields_set__:
            try:
                value = getattr(self, name)
            except Exception:
                continue

            tokens.append(f"{name}={value!r}")
            tokens.append(", ")

        if tokens and tokens[-1] == ", ":
            tokens.pop()

        tokens.append(")")
        return "".join(tokens)

    @override
    def __str__(self) -> str:
        return self.__repr__()


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


def __validate_email_str(value: str) -> str:
    from email_validator import validate_email

    validated = validate_email(value, check_deliverability=False)
    return validated.normalized.lower()


EmailStr: TypeAlias = Annotated[
    str,
    AfterValidator(__validate_email_str),
]

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


_order_cache: dict[tuple[type[OrderedStrEnum], str], int] = {}


class OrderedStrEnum(StrEnum):
    @classmethod
    def __order_mapping__(cls) -> dict[Any, int]:
        return {}

    @property
    def order(self) -> int:
        key = (type(self), self)
        value = _order_cache.get(key)
        if value is not None:
            return value

        value = self.__order_mapping__().get(self)
        if value is None:
            value = tuple(type(self)).index(self)

        _order_cache[key] = value
        return value

    @override
    def __lt__(self, __x: str | None) -> bool:
        if __x is None:
            return False

        if isinstance(__x, OrderedStrEnum):
            return self.order < __x.order

        return super().__lt__(__x)

    @override
    def __le__(self, __x: str | None) -> bool:
        if __x is None:
            return False

        if isinstance(__x, OrderedStrEnum):
            return self.order <= __x.order

        return super().__le__(__x)

    @override
    def __gt__(self, __x: str | None) -> bool:
        if __x is None:
            return True

        if isinstance(__x, OrderedStrEnum):
            return self.order > __x.order

        return super().__gt__(__x)

    @override
    def __ge__(self, __x: str | None) -> bool:
        if __x is None:
            return True

        if isinstance(__x, OrderedStrEnum):
            return self.order >= __x.order

        return super().__ge__(__x)


@runtime_checkable
class _SupportsAssignedFieldsTracking(Protocol):
    __pydantic_fields__: ClassVar[dict[str, FieldInfo]]
    __pydantic_fields_set__: set[str]


def get_assigned_fields(obj: _SupportsAssignedFieldsTracking, /) -> set[str]:
    return obj.__pydantic_fields_set__


def get_assigned_values(obj: _SupportsAssignedFieldsTracking, /) -> dict[str, Any]:
    fields = get_assigned_fields(obj)
    values: dict[str, Any] = {}

    for field in fields:
        try:
            values[field] = getattr(obj, field)
        except AttributeError:
            pass

    return values


def is_assigned(obj: _SupportsAssignedFieldsTracking, field: str, /) -> bool:
    return field in get_assigned_fields(obj)


def defaulting[T: _SupportsAssignedFieldsTracking](
    original: T,
    defaults: T | dict[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> T:
    if defaults is None:
        return original

    is_mapping = util.is_mapping(defaults)

    update: dict[str, Any] = {}
    original_fields = get_assigned_fields(original)
    defaults_fields = get_assigned_fields(defaults) if not is_mapping else defaults.keys()

    for field in defaults_fields:
        if field not in original_fields:
            try:
                update[field] = getattr(defaults, field) if not is_mapping else defaults[field]
            except AttributeError:
                pass

    for key, value in kwargs.items():
        if key not in original_fields and key not in update:
            update[key] = value

    if isinstance(original, BaseModel):
        return original.model_copy(update=update)
    else:
        return dataclasses.replace(original, **update)  # type: ignore


def replacing[T: _SupportsAssignedFieldsTracking](
    original: T,
    overrides: T | dict[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> T:
    if overrides is None:
        return original

    update = overrides if util.is_mapping(overrides) else get_assigned_values(overrides)
    update.update(kwargs)

    if isinstance(original, BaseModel):
        return original.model_copy(update=update)
    else:
        return dataclasses.replace(
            original,  # type: ignore
            **update,
        )


def WithDefaults(
    defaults: _SupportsAssignedFieldsTracking
    | Callable[[], _SupportsAssignedFieldsTracking]
    | None = None,
    /,
    **kwargs: Any,
) -> AfterValidator:
    if callable(defaults):
        defaults = defaults()

    def WithDefaults(obj: object) -> Any:
        if not isinstance(obj, _SupportsAssignedFieldsTracking):
            raise TypeError(
                "`WithDefaults` can only be applied to types with assigned fields tracking, such as `BaseModel` or `ValidatedDataclass` instances."
            )

        return defaulting(obj, defaults, **kwargs)

    return AfterValidator(WithDefaults)


_REGEX_FLAG_CHARACTERS = set(member for member in RegexFlag.__members__ if len(member) == 1)


def _pre_validate_regex_flags(value: object) -> object:
    if isinstance(value, str):
        value = value.upper()
        try:
            return RegexFlag[value]
        except KeyError:
            pass

        summed = RegexFlag.NOFLAG
        for character in value:
            try:
                summed |= RegexFlag[character]
            except KeyError:
                raise ValueError(
                    f"invalid regex flag character '{character}', must be one of: {_REGEX_FLAG_CHARACTERS}"
                )

        return summed

    return value


RegexFlags = Annotated[RegexFlag, BeforeValidator(_pre_validate_regex_flags)]
