from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Self

from pydantic_core.core_schema import (
    no_info_plain_validator_function,
    plain_serializer_function_ser_schema,
)

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
    from pydantic_core import CoreSchema


def _native_descriptor(cls: type, field: str) -> Any:
    """Find the native class descriptor for a field, skipping Python-side wrappers.

    A subclass chain can hold both wrapped properties and native getters for the same field,
    and a native subclass may override its parent's getter. Resolving from the first class
    that defines the field outside the Python wrapper classes always finds the most derived
    native descriptor.
    """
    for base in cls.__mro__:
        if issubclass(base, RustConfigModel):
            continue

        if field in vars(base):
            return vars(base)[field]

    raise TypeError(f"{cls.__name__} has no native descriptor for field {field!r}")


def _wrapping_property(descriptor: Any, wrap: Callable[[Any], Any]) -> property:
    """Build a property reading through a native getter and wrapping its value."""

    def read(self: Any) -> Any:
        return wrap(descriptor.__get__(self, type(self)))

    return property(read)


class RustConfigModel:
    """Wire a Rust-backed configuration class into Pydantic.

    The Rust class carries the fields, validation, and serialization. This mix-in only teaches
    Pydantic to route through them, validating mappings via the class constructor, serializing
    via `to_dict`, and describing itself via `json_schema`.

    A subclass may declare `__field_wrappers__` mapping field names to callables. Each named
    field's getter is wrapped so its value converts on the way out, which turns native enum
    values back into their Python enum types.

    A subclass belonging to a tagged union declares its selector value as `__type_tag__`. The
    native constructor carries no `type` parameter, so validation checks and strips a mapping's
    `type` key against the tag before construction.
    """

    __field_wrappers__: ClassVar[Mapping[str, Callable[[Any], Any]]] = {}
    __type_tag__: ClassVar[str | None] = None

    if TYPE_CHECKING:

        def __to_dict__(self) -> dict[str, Any]: ...

        @staticmethod
        def __json_schema__() -> dict[str, Any]: ...

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for field, wrapper in cls.__field_wrappers__.items():
            setattr(cls, field, _wrapping_property(_native_descriptor(cls, field), wrapper))

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        """Build a schema validating mappings through the Rust constructor."""

        def validate(value: Any) -> Any:
            if isinstance(value, cls):
                return value

            if isinstance(value, Mapping):
                if cls.__type_tag__ is not None and "type" in value:
                    value = dict(value)
                    tag = value.pop("type")
                    if tag != cls.__type_tag__:
                        raise ValueError(
                            f"type must be {cls.__type_tag__!r} for {cls.__name__}, "
                            f"got {str(tag)!r}"
                        )

                return cls(**value)

            raise ValueError(f"value must be a mapping or a {cls.__name__} instance")

        return no_info_plain_validator_function(
            validate,
            serialization=plain_serializer_function_ser_schema(cls.__to_dict__),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> dict[str, Any]:
        """Return the JSON Schema the Rust side derives for this section."""
        return cls.__json_schema__()

    def __copy__(self) -> Self:
        """Return the instance itself, configuration values are immutable."""
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """Return the instance itself, configuration values are immutable."""
        return self
