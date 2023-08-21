import importlib
import json
import traceback
from abc import ABC
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Literal, cast

import pydantic
import pydantic.generics
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    constr,
)
from pydantic.fields import FieldInfo
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema
from pydantic_core.core_schema import no_info_before_validator_function
from typing_extensions import Self, dataclass_transform

from ceres.internal.utilities import (
    PydanticDataclassLike,
    decode_td,
    get_type_adapter,
    is_pydantic_dataclass_type,
    strify,
)


def jsonify(obj: object, **kwargs: Any) -> str:
    return get_type_adapter(type(obj)).dump_json(obj, **kwargs).decode()


def simplify(obj: object) -> Any:
    return json.loads(jsonify(obj))


NAME_TYPE_PATTERN = r"^[a-zA-Z_\-][a-zA-Z0-9_\-]*$"

NameType = constr(pattern=NAME_TYPE_PATTERN)
NonEmptyStrType = constr(min_length=1)
NonBlankStrType = constr(min_length=1, pattern=r".*\S.*")


class DateType(date):
    pass


class DateTimeType(datetime):
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        return no_info_before_validator_function(cls.validate, handler(datetime))

    @classmethod
    def validate(cls, value: Any) -> datetime | None:
        if value is None:
            return None

        timestamp = get_type_adapter(datetime | date).validate_python(value)
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
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        return no_info_before_validator_function(cls.validate, handler(Any))

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
    __slots__ = ("__text",)

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls, handler(Any), serialization=core_schema.to_string_ser_schema()
        )

    def __get_pydantic_json_schema__(
        self,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        json_schema = handler(core_schema)
        json_schema["type"] = "string"
        return json_schema

    def __init__(self, obj: str | type | Self, /) -> None:  # type: ignore
        if isinstance(obj, ClassPath):
            cls = obj.cls
            text = obj.__text
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

        self.__text = text

    def __str__(self) -> str:
        return self.__text

    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(self.__text)})"

    def __eq__(self, obj: object) -> bool:
        return isinstance(obj, ClassPath) and self.__text == obj.__text

    def __hash__(self) -> int:
        return hash(self.__text)

    @property
    def cls(self) -> type:
        return _load_cls_from_cls_path(self.__text)


if TYPE_CHECKING:
    Name = str
    NonEmptyStr = str
    NonBlankStr = str
    Date = date
    DateTime = datetime
    TimeDelta = timedelta
    PositiveTimeDelta = timedelta
    NonNegativeTimeDelta = timedelta
else:
    Name = NameType
    NonEmptyStr = NonEmptyStrType
    NonBlankStr = NonBlankStrType
    Date = DateType
    DateTime = DateTimeType
    TimeDelta = TimeDeltaType
    PositiveTimeDelta = PositiveTimeDeltaType
    NonNegativeTimeDelta = NonNegativeTimeDeltaType


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
