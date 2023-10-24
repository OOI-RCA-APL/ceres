from typing import Literal, Sequence

from ceres.address import Address
from ceres.data import DataObject, ImmutableDataObject
from ceres.internal.utilities import StrEnum
from ceres.validation import ValidationProblem


class Error(ImmutableDataObject):
    type: str


class ComponentErrorType(StrEnum):
    CLASS_INVALID = "component-class-invalid-error"
    MODULE_NOT_FOUND = "component-module-not-found-error"
    MODULE_EXCEPTION = "component-module-exception-error"
    CLASS_NOT_FOUND = "component-class-not-found-error"
    INIT_EXCEPTION = "component-init-exception-error"
    PARAMETERS_INVALID = "component-parameters-invalid-error"
    REFERENCE_INVALID = "component-reference-invalid-error"
    JOB_INVALID = "component-job-invalid-error"


class BaseComponentError(Error):
    type: ComponentErrorType
    message: str


class ComponentModuleNotFoundError(BaseComponentError):
    type: Literal[ComponentErrorType.MODULE_NOT_FOUND] = ComponentErrorType.MODULE_NOT_FOUND


class ComponentModuleExceptionError(BaseComponentError):
    type: Literal[ComponentErrorType.MODULE_EXCEPTION] = ComponentErrorType.MODULE_EXCEPTION
    traceback: Sequence[str]


class ComponentClassNotFoundError(BaseComponentError):
    type: Literal[ComponentErrorType.CLASS_NOT_FOUND] = ComponentErrorType.CLASS_NOT_FOUND


class ComponentClassInvalidError(BaseComponentError):
    type: Literal[ComponentErrorType.CLASS_INVALID] = ComponentErrorType.CLASS_INVALID


class ComponentParametersInvalidError(BaseComponentError):
    type: Literal[ComponentErrorType.PARAMETERS_INVALID] = ComponentErrorType.PARAMETERS_INVALID
    problems: Sequence[ValidationProblem]


class ComponentInitExceptionError(BaseComponentError):
    type: Literal[ComponentErrorType.INIT_EXCEPTION] = ComponentErrorType.INIT_EXCEPTION
    traceback: Sequence[str]


class ComponentReferenceInvalidError(BaseComponentError):
    type: Literal[ComponentErrorType.REFERENCE_INVALID] = ComponentErrorType.REFERENCE_INVALID


class ComponentJobInvalidError(BaseComponentError):
    type: Literal[ComponentErrorType.JOB_INVALID] = ComponentErrorType.JOB_INVALID


ComponentError = (
    ComponentModuleNotFoundError
    | ComponentModuleExceptionError
    | ComponentClassNotFoundError
    | ComponentClassInvalidError
    | ComponentParametersInvalidError
    | ComponentInitExceptionError
    | ComponentReferenceInvalidError
    | ComponentJobInvalidError
)


class ConfigErrorType(StrEnum):
    NOT_PROVIDED = "config-not-provided-error"
    READ_ERROR = "config-read-error"
    PARSE_ERROR = "config-parse-error"
    VALIDATION_ERROR = "config-validation-error"
    DATABASE_ERROR = "config-database-error"
    COMPONENT_ERROR = "config-component-error"
    REFERENCE_ERROR = "config-reference-error"


class BaseConfigError(Error):
    pass


class ConfigNotProvidedError(BaseConfigError):
    type: Literal[ConfigErrorType.NOT_PROVIDED] = ConfigErrorType.NOT_PROVIDED
    message: str


class ConfigReadError(BaseConfigError):
    type: Literal[ConfigErrorType.READ_ERROR] = ConfigErrorType.READ_ERROR
    message: str


class ConfigParseErrorLocation(DataObject):
    line: int
    column: int


class ConfigParseError(BaseConfigError):
    type: Literal[ConfigErrorType.PARSE_ERROR] = ConfigErrorType.PARSE_ERROR
    message: str | None = None
    location: ConfigParseErrorLocation | None = None


class ConfigValidationError(BaseConfigError):
    type: Literal[ConfigErrorType.VALIDATION_ERROR] = ConfigErrorType.VALIDATION_ERROR
    problems: Sequence[ValidationProblem]


class ConfigDatabaseError(BaseConfigError):
    type: Literal[ConfigErrorType.DATABASE_ERROR] = ConfigErrorType.DATABASE_ERROR
    message: str
    exception: str


class ConfigComponentError(BaseConfigError):
    type: Literal[ConfigErrorType.COMPONENT_ERROR] = ConfigErrorType.COMPONENT_ERROR
    component: Address
    error: ComponentError


ConfigError = (
    ConfigNotProvidedError
    | ConfigReadError
    | ConfigParseError
    | ConfigValidationError
    | ConfigDatabaseError
    | ConfigComponentError
)


class ReloadErrorType(StrEnum):
    CONFIG_INVALID = "reload-config-invalid-error"
    ALREADY_ACTIVE = "reload-already-active-error"


class BaseReloadError(Error):
    pass


class ReloadConfigInvalidError(BaseReloadError):
    type: Literal[ReloadErrorType.CONFIG_INVALID] = ReloadErrorType.CONFIG_INVALID
    errors: Sequence[ConfigError]


class ReloadAlreadyActiveError(BaseReloadError):
    type: Literal[ReloadErrorType.ALREADY_ACTIVE] = ReloadErrorType.ALREADY_ACTIVE


ReloadError = ReloadConfigInvalidError | ReloadAlreadyActiveError


class ProcedureErrorType(StrEnum):
    UNIT_DOES_NOT_EXIST = "procedure-unit-does-not-exist-error"
    COMPONENT_DOES_NOT_EXIST = "procedure-component-does-not-exist-error"
    COMPONENT_NOT_LOADED = "procedure-component-not-loaded-error"
    DOES_NOT_EXIST = "procedure-does-not-exist-error"
    INVALID_ARGUMENTS = "procedure-invalid-arguments-error"
    NOT_SUBSCRIBABLE = "procedure-not-subscribable-error"
    CANCELLED = "procedure-cancelled-error"
    INTERNAL = "procedure-internal-error"


class BaseProcedureError(Error):
    type: ProcedureErrorType


class ProcedureUnitDoesNotExistError(BaseProcedureError):
    type: Literal[ProcedureErrorType.UNIT_DOES_NOT_EXIST] = ProcedureErrorType.UNIT_DOES_NOT_EXIST


class ProcedureComponentDoesNotExistError(BaseProcedureError):
    type: Literal[
        ProcedureErrorType.COMPONENT_DOES_NOT_EXIST
    ] = ProcedureErrorType.COMPONENT_DOES_NOT_EXIST


class ProcedureComponentNotLoadedError(BaseProcedureError):
    type: Literal[ProcedureErrorType.COMPONENT_NOT_LOADED] = ProcedureErrorType.COMPONENT_NOT_LOADED


class ProcedureDoesNotExistError(BaseProcedureError):
    type: Literal[ProcedureErrorType.DOES_NOT_EXIST] = ProcedureErrorType.DOES_NOT_EXIST


class ProcedureInvalidArgumentsError(BaseProcedureError):
    type: Literal[ProcedureErrorType.INVALID_ARGUMENTS] = ProcedureErrorType.INVALID_ARGUMENTS
    problems: Sequence[ValidationProblem]


class ProcedureNotSubscribableError(BaseProcedureError):
    type: Literal[ProcedureErrorType.NOT_SUBSCRIBABLE] = ProcedureErrorType.NOT_SUBSCRIBABLE


class ProcedureCancelledError(BaseProcedureError):
    type: Literal[ProcedureErrorType.CANCELLED] = ProcedureErrorType.CANCELLED


class ProcedureInternalError(BaseProcedureError):
    type: Literal[ProcedureErrorType.INTERNAL] = ProcedureErrorType.INTERNAL
    traceback: Sequence[str]


ProcedureError = (
    ProcedureUnitDoesNotExistError
    | ProcedureUnitDoesNotExistError
    | ProcedureComponentDoesNotExistError
    | ProcedureDoesNotExistError
    | ProcedureComponentNotLoadedError
    | ProcedureInvalidArgumentsError
    | ProcedureNotSubscribableError
    | ProcedureCancelledError
    | ProcedureInternalError
)
