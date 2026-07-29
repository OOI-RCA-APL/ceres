from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self

from pydantic_core.core_schema import (
    no_info_plain_validator_function,
    plain_serializer_function_ser_schema,
)

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
    from pydantic_core import CoreSchema


class RustConfigModel:
    """Wire a Rust-backed configuration class into Pydantic.

    The Rust class carries the fields, validation, and serialization. This mix-in only teaches
    Pydantic to route through them, validating mappings via the class constructor, serializing
    via `to_dict`, and describing itself via `json_schema`.
    """

    if TYPE_CHECKING:

        def to_dict(self) -> dict[str, Any]: ...

        @staticmethod
        def json_schema() -> dict[str, Any]: ...

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
            serialization=plain_serializer_function_ser_schema(cls.to_dict),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> dict[str, Any]:
        """Return the JSON Schema the Rust side derives for this section."""
        return cls.json_schema()

    def __copy__(self) -> Self:
        """Copy by reconstructing from the serialized form."""
        return type(self)(**self.to_dict())

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """Deep-copy by reconstructing from the serialized form."""
        return type(self)(**self.to_dict())
