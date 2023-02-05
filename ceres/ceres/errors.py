from enum import Enum
from typing import Literal, Sequence

from .address import Address
from .data import DataObject, ImmutableDataObject
from .validation import ValidationProblem


class Error(ImmutableDataObject):
    kind: str


class ComponentErrorKind(str, Enum):
    CLASS_INVALID = "component-class-invalid"
    MODULE_NOT_FOUND = "component-module-not-found"
    MODULE_EXCEPTION = "component-module-exception"
    CLASS_NOT_FOUND = "component-class-not-found"
    INIT_EXCEPTION = "component-init-exception"
    PARAMETERS_INVALID = "component-parameters-invalid"
    REFERENCE_INVALID = "component-reference-invalid"


class BaseComponentError(Error):
    kind: ComponentErrorKind
    message: str


class ComponentModuleNotFoundError(BaseComponentError):
    kind: Literal[ComponentErrorKind.MODULE_NOT_FOUND] = ComponentErrorKind.MODULE_NOT_FOUND


class ComponentModuleExceptionError(BaseComponentError):
    kind: Literal[ComponentErrorKind.MODULE_EXCEPTION] = ComponentErrorKind.MODULE_EXCEPTION
    traceback: Sequence[str]


class ComponentClassNotFoundError(BaseComponentError):
    kind: Literal[ComponentErrorKind.CLASS_NOT_FOUND] = ComponentErrorKind.CLASS_NOT_FOUND


class ComponentClassInvalidError(BaseComponentError):
    kind: Literal[ComponentErrorKind.CLASS_INVALID] = ComponentErrorKind.CLASS_INVALID


class ComponentParametersInvalidError(BaseComponentError):
    kind: Literal[ComponentErrorKind.PARAMETERS_INVALID] = ComponentErrorKind.PARAMETERS_INVALID
    problems: Sequence[ValidationProblem]


class ComponentInitExceptionError(BaseComponentError):
    kind: Literal[ComponentErrorKind.INIT_EXCEPTION] = ComponentErrorKind.INIT_EXCEPTION
    traceback: Sequence[str]


class ComponentReferenceInvalidError(BaseComponentError):
    kind: Literal[ComponentErrorKind.REFERENCE_INVALID] = ComponentErrorKind.REFERENCE_INVALID


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
    READ_ERROR = "config-read-error"
    PARSE_ERROR = "config-parse-error"
    VALIDATION_ERROR = "config-validation-error"
    DATABASE_ERROR = "config-database-error"
    COMPONENT_ERROR = "config-component-error"
    REFERENCE_ERROR = "config-reference-error"


class BaseConfigError(Error):
    pass


class ConfigReadError(BaseConfigError):
    kind: Literal[ConfigErrorKind.READ_ERROR] = ConfigErrorKind.READ_ERROR
    message: str


class ConfigParseErrorLocation(DataObject):
    line: int
    column: int


class ConfigParseError(BaseConfigError):
    kind: Literal[ConfigErrorKind.PARSE_ERROR] = ConfigErrorKind.PARSE_ERROR
    message: str | None = None
    location: ConfigParseErrorLocation | None = None


class ConfigValidationError(BaseConfigError):
    kind: Literal[ConfigErrorKind.VALIDATION_ERROR] = ConfigErrorKind.VALIDATION_ERROR
    problems: Sequence[ValidationProblem]


class ConfigDatabaseError(BaseConfigError):
    kind: Literal[ConfigErrorKind.DATABASE_ERROR] = ConfigErrorKind.DATABASE_ERROR
    message: str
    exception: str


class ConfigComponentError(BaseConfigError):
    kind: Literal[ConfigErrorKind.COMPONENT_ERROR] = ConfigErrorKind.COMPONENT_ERROR
    component: Address
    error: ComponentError


ConfigError = (
    ConfigReadError
    | ConfigParseError
    | ConfigValidationError
    | ConfigDatabaseError
    | ConfigComponentError
)


class ReloadErrorKind(str, Enum):
    CONFIG_INVALID = "reload-config-invalid"
    ALREADY_ACTIVE = "reload-already-active"


class BaseReloadError(Error):
    pass


class ReloadConfigInvalidError(BaseReloadError):
    kind: Literal[ReloadErrorKind.CONFIG_INVALID] = ReloadErrorKind.CONFIG_INVALID
    errors: Sequence[ConfigError]


class ReloadAlreadyActiveError(BaseReloadError):
    kind: Literal[ReloadErrorKind.ALREADY_ACTIVE] = ReloadErrorKind.ALREADY_ACTIVE


ReloadError = ReloadConfigInvalidError | ReloadAlreadyActiveError


class ProcedureErrorKind(str, Enum):
    UNIT_DOES_NOT_EXIST = "procedure-unit-does-not-exist"
    COMPONENT_DOES_NOT_EXIST = "procedure-component-does-not-exist"
    COMPONENT_NOT_LOADED = "procedure-component-not-loaded"
    DOES_NOT_EXIST = "procedure-does-not-exist"
    INVALID_INPUT = "procedure-invalid-input"
    CANCELLED = "procedure-cancelled"
    EXCEPTION = "procedure-exception"


class BaseProcedureError(Error):
    kind: ProcedureErrorKind


class ProcedureUnitDoesNotExistError(BaseProcedureError):
    kind: Literal[ProcedureErrorKind.UNIT_DOES_NOT_EXIST] = ProcedureErrorKind.UNIT_DOES_NOT_EXIST


class ProcedureComponentDoesNotExistError(BaseProcedureError):
    kind: Literal[
        ProcedureErrorKind.COMPONENT_DOES_NOT_EXIST
    ] = ProcedureErrorKind.COMPONENT_DOES_NOT_EXIST


class ProcedureComponentNotLoadedError(BaseProcedureError):
    kind: Literal[ProcedureErrorKind.COMPONENT_NOT_LOADED] = ProcedureErrorKind.COMPONENT_NOT_LOADED


class ProcedureDoesNotExistError(BaseProcedureError):
    kind: Literal[ProcedureErrorKind.DOES_NOT_EXIST] = ProcedureErrorKind.DOES_NOT_EXIST


class ProcedureInvalidInputError(BaseProcedureError):
    kind: Literal[ProcedureErrorKind.INVALID_INPUT] = ProcedureErrorKind.INVALID_INPUT
    problems: Sequence[ValidationProblem]


class ProcedureCancelledError(BaseProcedureError):
    kind: Literal[ProcedureErrorKind.CANCELLED] = ProcedureErrorKind.CANCELLED


class ProcedureExceptionError(BaseProcedureError):
    kind: Literal[ProcedureErrorKind.EXCEPTION] = ProcedureErrorKind.EXCEPTION
    traceback: Sequence[str]


ProcedureError = (
    ProcedureUnitDoesNotExistError
    | ProcedureUnitDoesNotExistError
    | ProcedureComponentDoesNotExistError
    | ProcedureDoesNotExistError
    | ProcedureComponentNotLoadedError
    | ProcedureInvalidInputError
    | ProcedureCancelledError
    | ProcedureExceptionError
)
