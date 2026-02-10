from __future__ import annotations

import dataclasses
import sys
from abc import ABCMeta
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableSet, Sequence, Set, Sized
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum as BaseStrEnum
from re import RegexFlag
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Final,
    NewType,
    Protocol,
    Self,
    TypeAlias,
    TypedDict,
    Unpack,
    cast,
    dataclass_transform,
    final,
    overload,
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
    PrivateAttr,
    StringConstraints,
    model_validator,
)
from pydantic.aliases import AliasChoices
from pydantic.fields import FieldInfo
from pydantic_core import (
    ArgsKwargs,
    CoreSchema,
    PydanticUndefined,
    SchemaSerializer,
    SchemaValidator,
)
from pydantic_extra_types.color import Color as Color
from pydantic_settings import NoDecode
from typing_extensions import TypeVar

from ceres._internal import util
from ceres._internal.util import (
    NAME_PATTERN,
    PydanticDataclassLike,
    cached_class_property,
    class_property,
    get_type_adapter,
    uniquify,
)

if TYPE_CHECKING:
    from inspect import Signature
    from types import CellType

    from pydantic.main import IncEx


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

_DATA_OBJECT_DEFAULT_CONFIG = ConfigDict(
    extra="forbid",
    use_attribute_docstrings=True,
    alias_generator=_DATA_OBJECT_ALIAS_GENERATOR,
    validate_by_name=True,
    validate_by_alias=True,
)


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


_patch_dataclass_fields()

if TYPE_CHECKING:
    from ceres.component import ConnectionField
else:
    ConnectionField = object


class DataModel(BaseModel):
    model_config = {**_DATA_OBJECT_DEFAULT_CONFIG}

    if TYPE_CHECKING:

        def __init__(self, **data: Any) -> None: ...

    def __init_subclass__(cls, **kwargs: Any) -> None:
        try:
            super().__init_subclass__(**kwargs)
        except Exception:
            super().__init_subclass__()

    @override
    def __setattr__(self, name: str, value: Any, /) -> None:
        super().__setattr__(name, value)
        self.model_fields_set.add(name)

    @override
    def __repr__(self) -> str:
        return _repr_of(self)

    @override
    def __str__(self) -> str:
        return self.__repr__()


class ImmutableDataModel(DataModel):
    model_config = ConfigDict(frozen=True)


_data_object_classes_being_built: set[Any] = set()


class DataObjectMetaclass(
    type(Protocol),
    ABCMeta,  # type: ignore
):
    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        *,
        init: None = None,
        repr: None = None,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool | None = None,
        config: ConfigDict | None = None,
        validate_on_init: bool | None = None,
        kw_only: bool = True,
        slots: bool = False,
        **kwargs: Any,
    ) -> type[DataObject]:
        if init is not None:
            raise ValueError(
                f"`{DataObject.__name__}` does support setting `init`. "
                "The `__init__` method is always generated."
            )
        if repr is not None:
            raise ValueError(
                f"`{DataObject.__name__}` does support setting `repr`. "
                f"The `__repr__` method is defined within the `{DataObject.__name__}` class. "
                "To customize `__repr__`, just define a new implementation in your subclass."
            )

        # `FrozenDataObject` may be undefined if it hasn't been built yet.
        try:
            Frozen = FrozenDataObject
        except NameError:
            Frozen = None

        if frozen is None:
            # Any subclass of `FrozenDataObject` is implicitly frozen.
            if Frozen is not None:
                frozen = any(issubclass(base, Frozen) for base in bases)
            else:
                frozen = False

        if frozen:
            # If `frozen` is set make sure `FrozenDataObject` is set the base classes.
            if Frozen is not None:
                # If `DataObject` is in the bases already, replace it with `FrozenDataObject`.
                bases = tuple(uniquify((Frozen if base is DataObject else base) for base in bases))
                # Ensure `FrozenDataObject` is in the bases if no subclass of it is already.
                if not any(issubclass(base, Frozen) for base in bases):
                    bases = tuple((Frozen, *bases))

        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        key = (cls.__module__, name)
        if key in _data_object_classes_being_built:
            return cls

        # Collect inherited Pydantic config from base classes with `__pydantic_config__` defined.
        inherited = ConfigDict()
        for base in reversed(bases):
            current: ConfigDict | None = getattr(base, "__pydantic_config__", None)
            if current:
                inherited.update(current)

        config: ConfigDict = {
            **inherited,
            "title": cls.__qualname__,
            **(config or {}),
        }

        # TODO: Use a more robust way to detect this.
        _data_object_classes_being_built.add(key)

        # Convert the class into a Pydantic dataclass.
        try:
            data_object_class = cast(
                "type[DataObject]",
                pydantic.dataclasses.dataclass(
                    repr=False,  # `DataObject` implements its own `__repr__`.
                    eq=eq,
                    order=order,
                    unsafe_hash=unsafe_hash,
                    frozen=frozen,
                    config=config,
                    validate_on_init=validate_on_init,
                    slots=slots,
                    kw_only=kw_only,
                )(cls),
            )

            data_object_class.__module__ = cls.__module__
            data_object_class.__name__ = cls.__name__
            data_object_class.__qualname__ = cls.__qualname__

            if slots:
                # TODO: Figure out how to avoid this hack.
                #
                # The generated Pydantic dataclass validator ends up being an entirely different
                # class, for some reason, when the dataclass has `slots=True`, and that class gets
                # passed as `cls` to all the field/model validators but misses all the class
                # attributes defined on the dataclass. So we copy them over here, for now.
                assert cls.__class__ is type(data_object_class)
                for attribute, value in data_object_class.__dict__.items():
                    if (
                        # Copy dataclass attributes.
                        attribute.startswith("__dataclass_")
                        # Copy Pydantic attributes.
                        or attribute.startswith("__pydantic_")
                        # Copy data object attributes.
                        or (attribute.startswith("__data_object_"))
                        or attribute == "__signature__"
                    ):
                        setattr(cls, attribute, value)
        finally:
            # if data_object_parameters is not None:
            #     data_object_parameters.frozen = False
            _data_object_classes_being_built.discard(key)

        # Reassign the `__classcell__` of the class body to the dataclass we've created rather
        # than the original `cls` that was created and assigned by `type.__new__`. Failing to do so
        # will cause `super()` to work incorrectly and weird things will start breaking with
        # confusing error messages and you'll feel sad and nobody wants that.
        __classcell__: CellType | None = namespace.get("__classcell__")
        if __classcell__ is not None:
            __classcell__.cell_contents = data_object_class

        return data_object_class


@final
class FieldsSet(MutableSet[str]):
    __slots__ = (
        "_cls",
        "_mask",
    )

    @overload
    def __init__(self, value: FieldsSet, /) -> None: ...
    @overload
    def __init__(self, value: type[DataObject], mask: int | None = None, /) -> None: ...
    @overload
    def __init__(self, value: type[DataObject], fields: bool | Iterable[str], /) -> None: ...

    def __init__(
        self,
        value: type[DataObject] | FieldsSet,
        fields: int | Iterable[str] | None = None,
        /,
    ) -> None:
        if isinstance(value, type) and issubclass(value, DataObject):
            self._cls = value
            mask = 0
        elif isinstance(value, FieldsSet):
            if fields is not None:
                raise ValueError(
                    f"Cannot specify mask/fields when copying from another `{type(self).__name__}`."
                )

            self._cls = value._cls
            mask = value.mask
        else:
            raise TypeError(
                f"Expected subclass of `{DataObject.__name__}` or another `{type(self).__name__}` "
                "as first argument."
            )

        if isinstance(fields, bool):
            mask = self._get_filled_mask() if fields else 0
        elif isinstance(fields, int):
            mask |= fields
        elif isinstance(fields, Iterable):
            mask |= self._to_mask(fields)
        elif fields is not None:
            raise TypeError("Expected `int`, `Iterable[str]` or `None` as second argument.")

        self._mask = self._truncate_mask(mask)

    @property
    def cls(self) -> type[DataObject]:
        return self._cls

    @property
    def mask(self) -> int:
        return self._mask

    @mask.setter
    def make(self, mask: int, /) -> None:
        self._mask = self._truncate_mask(mask)

    @override
    def add(self, value: str) -> None:
        self._set_field(value)

    @override
    def discard(self, value: str) -> None:
        self._clear_field(value)

    @override
    def clear(self) -> None:
        self._mask = 0

    def fill(self) -> None:
        self._mask = self._get_filled_mask()

    @override
    def pop(self) -> str:
        for index in self._get_set_indexes():
            field = self._get_field(index)
            if field is not None:
                self._clear_index(index)
                return field

        raise KeyError("pop from an empty set")

    @override
    def remove(self, value: str) -> None:
        if value not in self:
            raise KeyError(value)

        self._clear_field(value)

    @override
    def __ior__(self, it: Set[str]) -> Self:
        self._mask |= self._to_mask(it)
        return self

    @override
    def __iand__(self, it: Set[Any]) -> Self:
        self._mask &= self._to_mask(it)
        return self

    @override
    def __ixor__(self, it: Set[_T]) -> Self:
        self._mask ^= self._to_mask(it)
        return self

    @override
    def __isub__(self, it: Set[Any]) -> Self:
        self._mask &= ~self._to_mask(it)
        return self

    @override
    def __contains__(self, field: Any) -> bool:
        index = self._get_index(field)
        if index is None:
            return False

        return self._is_index_set(index)

    @override
    def __iter__(self) -> Iterator[str]:
        return self._get_set_fields()

    @override
    def __len__(self) -> int:
        return self._mask.bit_count()

    def __bool__(self) -> bool:
        return self._mask != 0

    def _get_filled_mask(self) -> int:
        return (1 << len(self._cls.__data_object_field_names__)) - 1

    def _truncate_mask(self, mask: int) -> int:
        return mask & self._get_filled_mask()

    @override
    def __le__(self, other: Set[Any]) -> bool:
        if len(self) > len(other):
            return False

        for field in self:
            if field not in other:
                return False

        return True

    @override
    def __lt__(self, other: Set[Any]) -> bool:
        if len(self) >= len(other):
            return False

        for field in self:
            if field not in other:
                return False

        return True

    @override
    def __gt__(self, other: Set[Any]) -> bool:
        return not self.__le__(other)

    @override
    def __ge__(self, other: Set[Any]) -> bool:
        return not self.__lt__(other)

    @override
    def __and__(self, other: Set[Any]) -> Self:
        return self._remask(self._mask & self._to_mask(other))

    @override
    def __or__(self, other: Set[str]) -> Self:  # type: ignore
        return self._remask(self._mask | self._to_mask(other))

    @override
    def __sub__(self, other: Set[Any]) -> Self:
        return self._remask(self._mask & ~self._to_mask(other))

    @override
    def __xor__(self, other: Set[_T]) -> Self:
        return self._remask(self._mask ^ self._to_mask(other))

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, set | frozenset | Set):
            return False

        return len(self) == len(other) and self._mask == self._to_mask(other)

    @override
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.cls.__name__}, {list(self)})"

    @override
    def __str__(self) -> str:
        return f"{{{', '.join(repr(current) for current in self)}}}"

    @override
    def isdisjoint(self, other: Iterable[Any]) -> bool:
        other = set(other)
        for value in other:
            if value in self:
                return False
        for field in self:
            if field in other:
                return False

        return True

    def copy(self) -> Self:
        return self.__class__(self._cls, self._mask)

    def __copy__(self) -> Self:
        return self.copy()

    def _to_mask(self, other: Iterable[Any], /) -> int:
        if isinstance(other, FieldsSet) and other._cls is self._cls:
            return other._mask

        mask = 0
        for field in other:
            index = self._get_index(field)
            if index is not None:
                mask |= 1 << index

        return mask

    def _remask(self, mask: int) -> Self:
        copy = self.copy()
        copy._mask = mask
        return copy

    def _get_bit(self, index: int) -> int:
        return self._mask & (1 << index)

    def _is_index_set(self, index: int) -> bool:
        return not not (self._mask & (1 << index))

    def _set_index(self, index: int) -> None:
        self._mask |= 1 << index

    def _set_field(self, field: str) -> None:
        index = self._get_index(field)
        if index is not None:
            self._set_index(index)

    def _clear_index(self, index: int) -> None:
        self._mask &= ~(1 << index)

    def _clear_field(self, field: str) -> None:
        index = self._get_index(field)
        if index is not None:
            self._clear_index(index)

    def _get_index(self, field: str) -> int | None:
        return self._cls.__data_object_field_indexes__.get(field)

    def _get_field(self, index: int) -> str | None:
        try:
            return self._cls.__data_object_field_names__[index]
        except IndexError:
            return None

    def _get_set_indexes(self) -> Iterator[int]:
        for index in range(self._mask.bit_length()):
            if self._get_bit(index):
                yield index

    def _get_set_fields(self) -> Iterator[str]:
        for index in self._get_set_indexes():
            name = self._get_field(index)
            if name is not None:
                yield name


assert issubclass(FieldsSet, Set)


def _stored_fields_of(
    obj: DataObject | DataModel | type[DataObject | DataModel],
) -> Iterator[tuple[str, FieldInfo]]:
    if isinstance(obj, type):
        fields = obj.__pydantic_fields__
        fields_set = None
    else:
        if TYPE_CHECKING:
            assert isinstance(obj, DataObject | DataModel)

        fields = type(obj).__pydantic_fields__
        fields_set = obj.__pydantic_fields_set__

    for name, field in fields.items():
        if field.init_var is True:
            continue
        if fields_set is not None and name not in fields_set:
            continue

        yield name, field


def _repr_of(obj: DataObject | DataModel) -> str:
    tokens: list[str] = [type(obj).__name__, "("]
    append = tokens.append

    for name, _ in _stored_fields_of(obj):
        try:
            value = getattr(obj, name)
        except Exception:
            continue

        append(name)
        append("=")
        append(repr(value))
        append(", ")

    if len(tokens) == 2:
        append(")")
    else:
        tokens[-1] = ")"

    return "".join(tokens)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(
        dataclasses.field,
        dataclasses.Field,
        Field,
        FieldInfo,
        PrivateAttr,
        ConnectionField,
    ),
)
class DataObject(
    metaclass=DataObjectMetaclass,
    config=_DATA_OBJECT_DEFAULT_CONFIG,
):
    __slots__ = (
        "__weakref__",
        "__data_object_fields_set__",
    )

    @class_property
    @classmethod
    def __data_object_fields__(cls) -> Mapping[str, FieldInfo]:
        return MappingProxyType(cls.__pydantic_fields__)

    @cached_class_property
    @classmethod
    def __data_object_field_indexes__(cls) -> Mapping[str, int]:
        return MappingProxyType(
            {field: index for index, field in enumerate(cls.__data_object_fields__)}
        )

    @cached_class_property
    @classmethod
    def __data_object_field_names__(cls) -> tuple[str, ...]:
        return tuple(cls.__data_object_fields__)

    @cached_class_property
    @classmethod
    def __data_object_reduced_slots__(cls) -> tuple[str, ...]:
        slots: dict[str, None] = {}

        for current in reversed(cls.__mro__):
            __slots__ = getattr(current, "__slots__", ())
            if isinstance(__slots__, str):
                __slots__ = (__slots__,)
            for slot in __slots__:
                slots[slot] = None

        if slots:
            # `__weakref__` probably doesn't need to be included.
            slots.pop("__weakref__", None)
            # `__dict__` will be handled separately.
            slots.pop("__dict__", None)
            # `__data_object_fields_set__` will be handled separately.
            slots.pop("__data_object_fields_set__", None)

        return tuple(slots)

    @cached_class_property
    @classmethod
    def Model(cls) -> type[DataModel]:
        return cls.__data_object_create_model_class__()

    @classmethod
    def __data_object_create_model_class__(cls, name: str | None = None) -> type[DataModel]:
        if name is None:
            name = f"{cls.__name__}.Model"
            __qualname__ = name
        else:
            __qualname__ = None

        bases: tuple[type[Any], ...] = tuple(
            [
                *(
                    base.Model
                    for base in cls.__bases__
                    if issubclass(base, DataObject)
                    and base not in (object, DataObject, FrozenDataObject)
                )
            ]
        )

        if not any(base for base in bases if issubclass(base, DataModel)):
            bases = tuple([DataModel, *bases])

        from pydantic._internal._decorators import (
            Decorator,
            DecoratorInfos,
            PydanticDescriptorProxy,
        )

        def get_copied_validator(name: str) -> Any:
            for current in cls.__mro__:
                if current is DataObject:
                    break

                value = current.__dict__.get(name, PydanticUndefined)
                if value is not PydanticUndefined:
                    return value

            return None

        decorator_descriptors: dict[str, Any] = {}
        decorator_infos: DecoratorInfos = cls.__pydantic_decorators__
        for decorator_type in dataclasses.fields(decorator_infos):
            decorators: dict[str, Decorator] = getattr(decorator_infos, decorator_type.name, {})
            for decorator_name, decorator in decorators.items():
                function = get_copied_validator(decorator_name)
                if function is None:
                    continue

                descriptor = PydanticDescriptorProxy(function, decorator.info)
                decorator_descriptors[decorator_name] = descriptor

        namespace = {
            "model_config": {**cls.__pydantic_config__},
            "__annotations__": {
                field_name: field.annotation
                for field_name, field in cls.__pydantic_fields__.items()
                if field.annotation is not None
            },
            **{name: field for name, field in cls.__pydantic_fields__.items()},
            **{name: descriptor for name, descriptor in decorator_descriptors.items()},
        }

        ModelMetaclass: Any = type(BaseModel)
        Model: type[DataModel] = ModelMetaclass(name, bases, namespace)
        Model.__qualname__ = __qualname__ or name
        Model.__module__ = cls.__module__
        Model.__doc__ = cls.__doc__

        return Model

    def __data_object_to_model__(self, *, revalidate: bool = False) -> DataModel:
        Model = self.__class__.Model
        fields_set = set(self.__data_object_fields_set__)
        values = {field: getattr(self, field) for field, _ in _stored_fields_of(self)}
        if revalidate:
            model = Model.model_validate(values)
            model.__pydantic_fields_set__ = fields_set
        else:
            model = Model.model_construct(fields_set, **values)

        return model

    @classmethod
    def __data_object_construct__(cls, *args: Any, **kwargs: Any) -> Self:
        instance = super().__new__(cls)
        _object_setattr(instance, "__data_object_fields_set__", FieldsSet(cls))
        return instance

    if TYPE_CHECKING:
        __data_object_fields_set__: FieldsSet
        """
        Set of field names that were explicitly set during initialization. Used for equivalent
        set/unset functionality as with Pydantic's `BaseModel`.
        """

        # Standard dataclass class attributes.
        __dataclass_fields__: ClassVar[dict[str, Any]]
        __dataclass_params__: ClassVar[Any]

        # Pydantic dataclass class attributes.
        __signature__: ClassVar[Signature]
        __pydantic_config__: ClassVar[ConfigDict]
        __pydantic_complete__: ClassVar[bool]
        __pydantic_core_schema__: ClassVar[CoreSchema]
        __pydantic_decorators__: ClassVar[Any]
        __pydantic_fields__: ClassVar[dict[str, FieldInfo]]
        __pydantic_serializer__: ClassVar[SchemaSerializer]
        __pydantic_validator__: ClassVar[SchemaValidator]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__()

    @property
    def __fields_set__(self) -> FieldsSet:
        return self.__data_object_fields_set__

    @property
    def __pydantic_fields_set__(self) -> FieldsSet:
        return self.__data_object_fields_set__

    @model_validator(mode="wrap")
    @classmethod
    def _init__fields_set__(
        cls,
        data: object,
        handler: ModelWrapValidatorHandler[Self],
    ) -> DataObject:
        if type(data) is cls:
            computed = cls.__data_object_fields_set__
        elif isinstance(data, Mapping | ArgsKwargs):
            computed = cls._compute_fields_set(data)
        else:
            fields_set: Set[str] | None = getattr(data, "__pydantic_fields_set__", None)
            if fields_set is not None:
                computed = cls._compute_fields_set(fields_set)
            else:
                computed = FieldsSet(cls, cls.__data_object_fields__.keys())

        instance = handler(data)
        if instance is not data:
            _object_setattr(instance, "__data_object_fields_set__", computed)

        return instance

    @classmethod
    def _compute_fields_set(cls, values: Set[str] | Mapping[str, Any] | ArgsKwargs) -> FieldsSet:
        output = FieldsSet(cls)

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
                    output.add(parameter.name)

            values = values.kwargs or {}

        # Taken from Pydantic's implementation.
        for name, field in cls.__pydantic_fields__.items():
            if field.alias is not None and field.alias in values:
                output.add(name)

            if (name not in output) and (field.validation_alias is not None):
                aliases: list[str | AliasPath] = (
                    field.validation_alias.choices
                    if isinstance(field.validation_alias, AliasChoices)
                    else [field.validation_alias]
                )

                for alias in aliases:
                    if isinstance(alias, str) and alias in values:
                        output.add(name)
                        break

                    if isinstance(alias, AliasPath):
                        value = alias.search_dict_for_path(cast("dict[str, Any]", values))
                        if value is not PydanticUndefined:
                            output.add(name)
                            break

            if name not in output:
                if name in values:
                    output.add(name)
                elif not field.is_required():
                    pass

        return output

    @override
    def __setattr__(self, name: str, value: Any, /) -> None:
        super().__setattr__(name, value)
        if name in self.__pydantic_fields__:
            self.__data_object_fields_set__.add(name)

    @override
    def __repr__(self) -> str:
        return _repr_of(self)

    @override
    def __str__(self) -> str:
        return self.__repr__()

    @override
    def __reduce__(self) -> _ReducedDataObject:
        cls = type(self)
        dictionary: dict | None = getattr(self, "__dict__", None)
        if dictionary:
            dictionary = dict(dictionary)

        slots = self.__data_object_reduced_slots__
        slots = [_object_getattribute(self, slot) for slot in slots] if slots else None

        return _reconstruct_data_object, (
            cls,
            dictionary,
            slots,
            self.__pydantic_fields_set__.mask,
        )


if sys.version_info < (3, 13):
    DataObject.__dataclass_params__.frozen = True
else:
    DataObject.__dataclass_params__.frozen = None

try:

    @dataclass_transform(
        kw_only_default=True,
        frozen_default=True,
        field_specifiers=(
            dataclasses.field,
            dataclasses.Field,
            Field,
            FieldInfo,
            PrivateAttr,
            ConnectionField,
        ),
    )
    class FrozenDataObject(DataObject, frozen=True):
        __slots__ = ()
finally:
    if sys.version_info < (3, 13):
        DataObject.__dataclass_params__.frozen = False


_ReducedDataObjectValues: TypeAlias = tuple[
    type[object],
    dict[str, Any] | None,
    list[Any] | None,
    int,
]
_ReducedDataObject: TypeAlias = tuple[Callable[..., Any], _ReducedDataObjectValues]

_object_getattribute: Final = object.__getattribute__
_object_setattr: Final = object.__setattr__


def _do[T: DataObject](
    cls: type[T],
    dictionary: dict[str, Any] | None,
    slots: list[Any] | None,
    fields_set_mask: int,
    /,
) -> T:
    instance = cls.__new__(cls)

    if dictionary:
        for attribute, value in dictionary.items():
            _object_setattr(instance, attribute, value)
    if slots:
        for attribute, value in zip(cls.__data_object_reduced_slots__, slots):
            _object_setattr(instance, attribute, value)

    _object_setattr(instance, "__data_object_fields_set__", FieldsSet(cls, fields_set_mask))
    return instance


_reconstruct_data_object: Final = _do


if TYPE_CHECKING:
    # This is just to ensure that `ValidatedDataclass` is recognized as a valid Pydantic dataclass
    # type for type checking purposes without actually inheriting from `typing.Protocol` which
    # inherits from `typing.Generic` and causes issues with `dataclasses.dataclass`.
    __ensure_is_pydantic_dataclass: type[PydanticDataclassLike] = DataObject

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

    @property
    def __pydantic_fields_set__(self) -> Set[str]: ...


def get_assigned_fields(obj: _SupportsAssignedFieldsTracking, /) -> Set[str]:
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
                "`WithDefaults` can only be applied to types with assigned fields tracking, such as `BaseModel` or `DataObject` instances."
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
