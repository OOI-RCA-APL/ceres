from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Self

from pydantic_core.core_schema import (
    no_info_plain_validator_function,
    plain_serializer_function_ser_schema,
)

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
    from pydantic_core import CoreSchema


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
    """

    __field_wrappers__: ClassVar[Mapping[str, Callable[[Any], Any]]] = {}

    if TYPE_CHECKING:

        def __to_dict__(self) -> dict[str, Any]: ...

        @staticmethod
        def __json_schema__() -> dict[str, Any]: ...

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for field, wrapper in cls.__field_wrappers__.items():
            setattr(cls, field, _wrapping_property(getattr(cls, field), wrapper))

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

    def _reconstruction_fields(self) -> dict[str, Any]:
        """Return the fields a copy rebuilds from, only the explicitly-set ones when known."""
        provided = getattr(self, "provided", None)
        if provided is not None:
            return provided()

        return self.__to_dict__()

    def __copy__(self) -> Self:
        """Copy by reconstructing from the serialized form."""
        return type(self)(**self._reconstruction_fields())

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """Deep-copy by reconstructing from the serialized form."""
        return type(self)(**self._reconstruction_fields())
