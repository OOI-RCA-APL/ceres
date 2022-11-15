from enum import Enum
from typing import Literal

from pydantic import ValidationError

from .address import ComponentAddress
from .utilities import VDC


class ValidationProblem(VDC, frozen=True):
    location: list[str | int]
    message: str
    kind: str

    @classmethod
    def extract(cls, error: ValidationError) -> list["ValidationProblem"]:
        return [
            ValidationProblem(
                location=list(error["loc"]),
                message=error["msg"],
                kind=error["type"],
            )
            for error in error.errors()
        ]


class Error(VDC, frozen=True):
    kind: str


class ComponentErrorKind(str, Enum):
    COMPONENT_CLASS_INVALID = "component-class-invalid"
    COMPONENT_MODULE_NOT_FOUND = "component-module-not-found"
    COMPONENT_MODULE_EXCEPTION = "component-module-exception"
    COMPONENT_CLASS_NOT_FOUND = "component-class-not-found"
    COMPONENT_INIT_EXCEPTION = "component-init-exception"
    COMPONENT_PARAMETERS_INVALID = "component-parameters-invalid"
    COMPONENT_REFERENCE_INVALID = "component-reference-invalid"


class BaseComponentError(Error, frozen=True):
    kind: ComponentErrorKind
    message: str


class ComponentModuleNotFoundError(BaseComponentError, frozen=True):
    kind: Literal[
        ComponentErrorKind.COMPONENT_MODULE_NOT_FOUND
    ] = ComponentErrorKind.COMPONENT_MODULE_NOT_FOUND


class ComponentModuleExceptionError(BaseComponentError, frozen=True):
    kind: Literal[
        ComponentErrorKind.COMPONENT_MODULE_EXCEPTION
    ] = ComponentErrorKind.COMPONENT_MODULE_EXCEPTION
    traceback: str


class ComponentClassNotFoundError(BaseComponentError, frozen=True):
    kind: Literal[
        ComponentErrorKind.COMPONENT_CLASS_NOT_FOUND
    ] = ComponentErrorKind.COMPONENT_CLASS_NOT_FOUND


class ComponentClassInvalidError(BaseComponentError, frozen=True):
    kind: Literal[
        ComponentErrorKind.COMPONENT_CLASS_INVALID
    ] = ComponentErrorKind.COMPONENT_CLASS_INVALID


class ComponentParametersInvalidError(BaseComponentError, frozen=True):
    kind: Literal[
        ComponentErrorKind.COMPONENT_PARAMETERS_INVALID
    ] = ComponentErrorKind.COMPONENT_PARAMETERS_INVALID
    problems: list[ValidationProblem]


class ComponentInitExceptionError(BaseComponentError, frozen=True):
    kind: Literal[
        ComponentErrorKind.COMPONENT_INIT_EXCEPTION
    ] = ComponentErrorKind.COMPONENT_INIT_EXCEPTION
    traceback: str


class ComponentReferenceInvalidError(BaseComponentError, frozen=True):
    kind: Literal[
        ComponentErrorKind.COMPONENT_REFERENCE_INVALID
    ] = ComponentErrorKind.COMPONENT_REFERENCE_INVALID


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


class BaseConfigError(Error, frozen=True):
    pass


class ConfigReadError(BaseConfigError, frozen=True):
    kind: Literal[ConfigErrorKind.READ_ERROR] = ConfigErrorKind.READ_ERROR
    message: str


class ConfigParseErrorLocation(VDC):
    line: int
    column: int


class ConfigParseError(BaseConfigError, frozen=True):
    kind: Literal[ConfigErrorKind.PARSE_ERROR] = ConfigErrorKind.PARSE_ERROR
    message: str | None = None
    location: ConfigParseErrorLocation | None = None


class ConfigValidationError(BaseConfigError, frozen=True):
    kind: Literal[ConfigErrorKind.VALIDATION_ERROR] = ConfigErrorKind.VALIDATION_ERROR
    problems: list[ValidationProblem]


class ConfigDatabaseError(BaseConfigError, frozen=True):
    kind: Literal[ConfigErrorKind.DATABASE_ERROR] = ConfigErrorKind.DATABASE_ERROR
    message: str
    exception: str


class ConfigComponentError(BaseConfigError, frozen=True):
    kind: Literal[ConfigErrorKind.COMPONENT_ERROR] = ConfigErrorKind.COMPONENT_ERROR
    component: ComponentAddress
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


class BaseReloadError(Error, frozen=True):
    pass


class ReloadConfigInvalidError(BaseReloadError, frozen=True):
    kind: Literal[ReloadErrorKind.CONFIG_INVALID] = ReloadErrorKind.CONFIG_INVALID
    errors: list[ConfigError]


class ReloadAlreadyActiveError(BaseReloadError, frozen=True):
    kind: Literal[ReloadErrorKind.ALREADY_ACTIVE] = ReloadErrorKind.ALREADY_ACTIVE


ReloadError = ReloadConfigInvalidError | ReloadAlreadyActiveError
