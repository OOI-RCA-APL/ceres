import importlib
import json
import traceback
from abc import ABC
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Annotated, Any, Callable, Literal, cast

import pydantic
import pydantic.generics
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    StringConstraints,
)
from pydantic.fields import FieldInfo
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema
from pydantic_extra_types.color import Color as Color
from typing_extensions import Self, dataclass_transform

from ceres.internal.utilities import (
    NAME_PATTERN,
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
