from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from pydantic import ValidationError

from .path import ComponentPath, LocalComponentPath


@dataclass(kw_only=True, frozen=True)
class ValidationProblem:
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
    COMPONENT_REFERENCE_INVALID = "component-reference-invalid"


@dataclass(kw_only=True, frozen=True)
class BaseComponentError:
    kind: ComponentErrorKind
    message: str


@dataclass(kw_only=True, frozen=True)
class ComponentModuleNotFoundError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_MODULE_NOT_FOUND
    ] = ComponentErrorKind.COMPONENT_MODULE_NOT_FOUND


@dataclass(kw_only=True, frozen=True)
class ComponentModuleExceptionError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_MODULE_EXCEPTION
    ] = ComponentErrorKind.COMPONENT_MODULE_EXCEPTION
    traceback: str


@dataclass(kw_only=True, frozen=True)
class ComponentClassNotFoundError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_CLASS_NOT_FOUND
    ] = ComponentErrorKind.COMPONENT_CLASS_NOT_FOUND


@dataclass(kw_only=True, frozen=True)
class ComponentClassInvalidError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_CLASS_INVALID
    ] = ComponentErrorKind.COMPONENT_CLASS_INVALID


@dataclass(kw_only=True, frozen=True)
class ComponentParametersInvalidError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_PARAMETERS_INVALID
    ] = ComponentErrorKind.COMPONENT_PARAMETERS_INVALID
    problems: list[ValidationProblem]


@dataclass(kw_only=True, frozen=True)
class ComponentInitExceptionError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_INIT_EXCEPTION
    ] = ComponentErrorKind.COMPONENT_INIT_EXCEPTION
    traceback: str


@dataclass(kw_only=True, frozen=True)
class ComponentReferenceInvalidError(BaseComponentError):
    kind: Literal[
        ComponentErrorKind.COMPONENT_REFERENCE_INVALID
    ] = ComponentErrorKind.COMPONENT_REFERENCE_INVALID
    reference: LocalComponentPath


ComponentError = (
    ComponentModuleNotFoundError
    | ComponentModuleExceptionError
    | ComponentClassNotFoundError
    | ComponentClassInvalidError
    | ComponentParametersInvalidError
    | ComponentInitExceptionError
    | ComponentReferenceInvalidError
)


class ConfigErrorKind(str, Enum):
    READ_ERROR = "read-error"
    PARSE_ERROR = "parse-error"
    VALIDATION_ERROR = "validation-error"
    DATABASE_ERROR = "database-error"
    COMPONENT_ERROR = "component-error"
    REFERENCE_ERROR = "reference-error"


@dataclass(kw_only=True, frozen=True)
class BaseConfigError:
    pass


@dataclass(kw_only=True, frozen=True)
class ConfigReadError(BaseConfigError):
    kind: Literal[ConfigErrorKind.READ_ERROR] = ConfigErrorKind.READ_ERROR
    message: str


@dataclass(kw_only=True, frozen=True)
class ConfigParseErrorLocation:
    line: int
    column: int


@dataclass(kw_only=True, frozen=True)
class ConfigParseError(BaseConfigError):
    kind: Literal[ConfigErrorKind.PARSE_ERROR] = ConfigErrorKind.PARSE_ERROR
    message: str | None = None
    location: ConfigParseErrorLocation | None = None


@dataclass(kw_only=True, frozen=True)
class ConfigValidationError(BaseConfigError):
    kind: Literal[ConfigErrorKind.VALIDATION_ERROR] = ConfigErrorKind.VALIDATION_ERROR
    problems: list[ValidationProblem]


@dataclass(kw_only=True, frozen=True)
class ConfigDatabaseError(BaseConfigError):
    kind: Literal[ConfigErrorKind.DATABASE_ERROR] = ConfigErrorKind.DATABASE_ERROR
    message: str
    exception: str


@dataclass(kw_only=True, frozen=True)
class ConfigComponentError(BaseConfigError):
    kind: Literal[ConfigErrorKind.COMPONENT_ERROR] = ConfigErrorKind.COMPONENT_ERROR
    component: ComponentPath
    error: ComponentError


ConfigError = (
    ConfigReadError
    | ConfigParseError
    | ConfigValidationError
    | ConfigDatabaseError
    | ConfigComponentError
)


class ReloadErrorKind(str, Enum):
    CONFIG_INVALID = "config-invalid"
    ALREADY_ACTIVE = "already-active"


@dataclass(kw_only=True, frozen=True)
class BaseReloadError:
    pass


@dataclass(kw_only=True, frozen=True)
class ReloadConfigInvalidError(BaseReloadError):
    kind: Literal[ReloadErrorKind.CONFIG_INVALID] = ReloadErrorKind.CONFIG_INVALID
    errors: list[ConfigError]


@dataclass(kw_only=True, frozen=True)
class ReloadAlreadyActiveError(BaseReloadError):
    kind: Literal[ReloadErrorKind.ALREADY_ACTIVE] = ReloadErrorKind.ALREADY_ACTIVE


ReloadError = ReloadConfigInvalidError | ReloadAlreadyActiveError
