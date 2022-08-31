from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel

from .path import ComponentPath
from .validation import ValidationProblem


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


class ComponentErrorKind(str, Enum):
    INVALID_COMPONENT_CLASS = "invalid-component-class"
    COMPONENT_MODULE_NOT_FOUND = "component-module-not-found"
    COMPONENT_MODULE_EXCEPTION = "component-module-exception"
    COMPONENT_CLASS_NOT_FOUND = "component-class-not-found"
    COMPONENT_INIT_EXCEPTION = "component-init-exception"
    INVALID_COMPONENT_PARAMETERS = "invalid-component-parameters"


class BaseComponentError(BaseModel):
    kind: ComponentErrorKind
    message: str


class InvalidComponentClassError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.INVALID_COMPONENT_CLASS
    ] = ComponentErrorKind.INVALID_COMPONENT_CLASS


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


class InvalidComponentParametersError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.INVALID_COMPONENT_PARAMETERS
    ] = ComponentErrorKind.INVALID_COMPONENT_PARAMETERS
    problems: list[ValidationProblem]


class ComponentInitExceptionError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_INIT_EXCEPTION
    ] = ComponentErrorKind.COMPONENT_INIT_EXCEPTION
    traceback: str


ComponentError = (
    InvalidComponentClassError
    | ComponentModuleNotFoundError
    | ComponentModuleExceptionError
    | ComponentClassNotFoundError
    | InvalidComponentParametersError
    | ComponentInitExceptionError
)
