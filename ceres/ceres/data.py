import importlib
import json
import re
import traceback
from abc import ABC
from datetime import date, datetime, timedelta, timezone
from re import Pattern
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, Callable, ForwardRef, Mapping, cast

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
from typing_extensions import Self, dataclass_transform, override

from ceres.internal.utilities import (
    PydanticDataclassLike,
    decode_td,
    dictify,
    is_pydantic_dataclass,
    strify,
)


def jsonify(obj: object, **kwargs: Any) -> str:
    default = kwargs.get("default")

    return json.dumps(
        obj,
        default=default if default is not None else pydantic_encoder,
        **kwargs,
    )


def simplify(obj: object) -> Any:
    return json.loads(jsonify(obj))


class NameType(ConstrainedStr):
    regex: Pattern[str] = re.compile(r"^[a-zA-Z_\-][a-zA-Z0-9_\-]*$")

    @classmethod
    def get_pattern(cls) -> str:
        return NameType.regex.pattern[1:-1]


class NonEmptyStrType(ConstrainedStr):
    min_length = 1


class NonBlankStrType(ConstrainedStr):
    min_length = 1

    @override
    @classmethod
    def validate(cls, value: Any) -> str:
        validated = super().validate(value)
        if not validated.strip():
            raise ValueError("must not be blank")

        return validated


class DateType(date):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> date | None:
        if value is None:
            return None

        return parse_obj_as(date, value)


class DateTimeType(datetime):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> datetime | None:
        if value is None:
            return None

        timestamp = parse_obj_as(datetime | date, value)
        if not isinstance(timestamp, datetime):
            return datetime(
                year=timestamp.year,
                month=timestamp.month,
                day=timestamp.day,
                tzinfo=timezone.utc,
            )

        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)

        return timestamp.astimezone(timezone.utc)


class TimeDeltaType(timedelta):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> timedelta | None:
        if value is None:
            return None

        return decode_td(value)


class PositiveTimeDeltaType(TimeDeltaType):
    @classmethod
    def validate(cls, value: Any) -> timedelta | None:
        duration = super().validate(value)
        if duration is None:
            return None

        if duration <= timedelta():
            raise ValueError("must be greater than zero")

        return duration


class NonNegativeTimeDeltaType(TimeDeltaType):
    @classmethod
    def validate(cls, value: Any) -> timedelta | None:
        duration = super().validate(value)
        if duration is None:
            return None

        if duration < timedelta():
            raise ValueError("must be greater than or equal to zero")

        return duration


def _get_cls_path(cls: type) -> str:
    module: str | None = cls.__module__
    if module is None or module == str.__module__:  # type: ignore
        return cls.__name__

    return module + "." + cls.__name__


def _load_cls_from_cls_path(path: str) -> type:
    last_dot_index = path.rindex(".")
    cls_module_path = path[:last_dot_index]
    cls_name = path[last_dot_index + 1 :]

    try:
        module = importlib.import_module(cls_module_path)
    except Exception as exception:
        if isinstance(exception, ModuleNotFoundError) and exception.name == cls_module_path:
            raise ValueError(f"module '{cls_module_path}' was not found")

        raise ValueError(
            f"module '{cls_module_path}' raised an exception during import: "
            f"{traceback.format_exc()}",
        )

    cls = getattr(module, cls_name, None)
    if cls is None:
        raise ValueError(f"module {module} does not contain class {cls_name}")
    if not isinstance(cls, type):
        raise ValueError(f"{path} is not a class, got {strify(cls)}")

    return cls


class ClassPath:
    __slots__ = ("_cls", "_text")

    def __init__(self, obj: str | type | Self, /) -> None:  # type: ignore
        if isinstance(obj, ClassPath):
            cls = obj._cls
            text = obj._text
        elif isinstance(obj, type):
            cls = obj
            text = _get_cls_path(obj)
        elif isinstance(obj, str):
            cls = _load_cls_from_cls_path(obj)
            text = obj
        else:
            raise ValueError(
                f"must an import path string, instance of {type} or another instance of "
                f"{strify(type(self))}"
            )

        if text is None:
            text = _get_cls_path(cls)

        self._cls = cls
        self._text = text

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(self._text)})"

    @property
    def cls(self) -> type:
        return self._cls

    @classmethod
    def __get_validators__(cls):
        yield cls

    @classmethod
    def __modify_schema__(cls, field_schema: dict[str, Any]):
        field_schema.update(type="string")


if TYPE_CHECKING:
    Name = str
    NonEmptyStr = str
    NonBlankStr = str
    Date = date
    DateTime = datetime
    TimeDelta = timedelta
    PositiveTimeDelta = timedelta
    NonNegativeTimeDelta = timedelta
    BytesPattern = Pattern[bytes]
    StrPattern = Pattern[str]
else:
    Name = NameType
    NonEmptyStr = NonEmptyStrType
    NonBlankStr = NonBlankStrType
    Date = DateType
    DateTime = DateTimeType
    TimeDelta = TimeDeltaType
    PositiveTimeDelta = PositiveTimeDeltaType
    NonNegativeTimeDelta = NonNegativeTimeDeltaType
    BytesPattern = Annotated[Pattern, Field(regex=b".*")]
    StrPattern = Annotated[Pattern, Field(regex=".*")]

JSON_ENCODERS: Mapping[type[Any] | str | ForwardRef, Callable[..., Any]] = MappingProxyType(
    {
        ClassPath: str,
    }
)


class DataObject(BaseModel, ABC):
    class Config(BaseConfig):
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        extra = Extra.forbid
        json_encoders = dict(JSON_ENCODERS)
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
VALIDATED_DATACLASS_DEFAULT_CONFIG = MappingProxyType(ConfigDict(**DataObject.__dict__))


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
