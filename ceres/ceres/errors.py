from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ValidationError

from .path import ComponentPath


class ValidationProblem(BaseModel):
    location: list[str | int]
    message: str
    kind: str

    @classmethod
    def extract(cls, error: ValidationError) -> list[ValidationProblem]:
        return [
            ValidationProblem(
                location=list(error["loc"]),
                message=error["msg"],
                kind=error["type"],
            )
            for error in error.errors()
        ]


class ComponentErrorKind(str, Enum):
    COMPONENT_CLASS_INVALID = "component-class-invalid"
    COMPONENT_MODULE_NOT_FOUND = "component-module-not-found"
    COMPONENT_MODULE_EXCEPTION = "component-module-exception"
    COMPONENT_CLASS_NOT_FOUND = "component-class-not-found"
    COMPONENT_INIT_EXCEPTION = "component-init-exception"
    COMPONENT_PARAMETERS_INVALID = "component-parameters-invalid"


class BaseComponentError(BaseModel):
    kind: ComponentErrorKind
    message: str


class ComponentModuleNotFoundError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_MODULE_NOT_FOUND
    ] = ComponentErrorKind.COMPONENT_MODULE_NOT_FOUND


class ComponentModuleExceptionError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_MODULE_EXCEPTION
    ] = ComponentErrorKind.COMPONENT_MODULE_EXCEPTION
    traceback: str


class ComponentClassNotFoundError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_CLASS_NOT_FOUND
    ] = ComponentErrorKind.COMPONENT_CLASS_NOT_FOUND


class ComponentClassInvalidError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_CLASS_INVALID
    ] = ComponentErrorKind.COMPONENT_CLASS_INVALID


class ComponentParametersInvalidError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_PARAMETERS_INVALID
    ] = ComponentErrorKind.COMPONENT_PARAMETERS_INVALID
    problems: list[ValidationProblem]


class ComponentInitExceptionError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_INIT_EXCEPTION
    ] = ComponentErrorKind.COMPONENT_INIT_EXCEPTION
    traceback: str


ComponentError = (
    ComponentModuleNotFoundError
    | ComponentModuleExceptionError
    | ComponentClassNotFoundError
    | ComponentClassInvalidError
    | ComponentParametersInvalidError
    | ComponentInitExceptionError
)


class ConfigErrorKind(str, Enum):
    READ_ERROR = "read-error"
    PARSE_ERROR = "parse-error"
    SCHEMA_ERROR = "schema-error"
    DATABASE_ERROR = "database-error"
    COMPONENT_ERROR = "component-error"


class ConfigReadError(BaseModel):
    kind: Literal[ConfigErrorKind.READ_ERROR] = ConfigErrorKind.READ_ERROR


class ConfigParseError(BaseModel):
    kind: Literal[ConfigErrorKind.PARSE_ERROR] = ConfigErrorKind.PARSE_ERROR


class ConfigSchemaError(BaseModel):
    kind: Literal[ConfigErrorKind.SCHEMA_ERROR] = ConfigErrorKind.SCHEMA_ERROR
    problems: list[ValidationProblem] = []


class ConfigDatabaseError(BaseModel):
    kind: Literal[ConfigErrorKind.DATABASE_ERROR] = ConfigErrorKind.DATABASE_ERROR
    message: str
    exception: str


class ConfigComponentError(BaseModel):
    kind: Literal[ConfigErrorKind.COMPONENT_ERROR] = ConfigErrorKind.COMPONENT_ERROR
    path: ComponentPath
    error: ComponentError


ConfigError = (
    ConfigReadError
    | ConfigParseError
    | ConfigSchemaError
    | ConfigDatabaseError
    | ConfigComponentError
)
