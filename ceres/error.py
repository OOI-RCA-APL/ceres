from __future__ import annotations

from abc import ABC
from typing import Any, Callable, ClassVar, Literal, Sequence

from pydantic import computed_field, model_serializer
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from ceres._internal.lazy import lazy_imports
from ceres.address import Address
from ceres.data import DataObject, ImmutableDataObject
from ceres.validation import ValidationProblem

with lazy_imports(__name__):
    from ceres._internal import util


class Error(ImmutableDataObject, ABC):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR

    @computed_field
    @property
    def __error__(self) -> Literal[True]:
        return True

    type: str

    @model_serializer(mode="wrap")
    def _serialize(self, inner: Callable[[Any], Any]) -> Any:
        result = inner(self)
        if isinstance(result, dict):
            result.pop("__error__", None)
            result = {"__error__": True, **result}

        return result


class __BaseComponentError(Error, ABC):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    message: str


class ComponentValidationError(__BaseComponentError):
    type: Literal["component-validation-error"] = "component-validation-error"
    problems: Sequence[ValidationProblem]


class ComponentInitExceptionError(__BaseComponentError):
    type: Literal["component-init-exception-error"] = "component-init-exception-error"
    traceback: Sequence[str]


class ComponentReferenceInvalidError(__BaseComponentError):
    type: Literal["component-reference-invalid-error"] = "component-reference-invalid-error"


class ComponentJobInvalidError(__BaseComponentError):
    type: Literal["component-job-invalid-error"] = "component-job-invalid-error"


ComponentError = (
    ComponentValidationError
    | ComponentInitExceptionError
    | ComponentReferenceInvalidError
    | ComponentJobInvalidError
)


class __BaseConfigError(Error, ABC):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR


class ConfigNotProvidedError(__BaseConfigError):
    type: Literal["config-not-provided-error"] = "config-not-provided-error"
    message: str


class ConfigReadError(__BaseConfigError):
    type: Literal["config-read-error"] = "config-read-error"
    message: str


class ConfigParseErrorLocation(DataObject):
    line: int
    column: int


class ConfigParseError(__BaseConfigError):
    type: Literal["config-parse-error"] = "config-parse-error"
    message: str | None = None
    location: ConfigParseErrorLocation | None = None


class ConfigValidationError(__BaseConfigError):
    type: Literal["config-validation-error"] = "config-validation-error"
    problems: Sequence[ValidationProblem]


class ConfigDatabaseError(__BaseConfigError):
    type: Literal["config-database-error"] = "config-database-error"
    message: str
    exception: str


class ConfigComponentError(__BaseConfigError):
    type: Literal["config-component-error"] = "config-component-error"
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


class __BaseReloadError(Error, ABC):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST


class ReloadConfigInvalidError(__BaseReloadError):
    type: Literal["reload-config-invalid-error"] = "reload-config-invalid-error"
    errors: Sequence[ConfigError]


class ReloadAlreadyActiveError(__BaseReloadError):
    type: Literal["reload-already-active-error"] = "reload-already-active-error"


ReloadError = ReloadConfigInvalidError | ReloadAlreadyActiveError


class __BaseProcedureError(Error, ABC):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST


class ProcedureComponentNotFoundError(__BaseProcedureError):
    type: Literal["procedure-component-not-found-error"] = "procedure-component-not-found-error"


class ProcedureNotFoundError(__BaseProcedureError):
    type: Literal["procedure-not-found-error"] = "procedure-not-found-error"


class ProcedureNotPermittedError(__BaseProcedureError):
    type: Literal["procedure-not-permitted-error"] = "procedure-not-permitted-error"


class ProcedureInvalidArgumentsError(__BaseProcedureError):
    type: Literal["procedure-invalid-arguments-error"] = "procedure-invalid-arguments-error"
    problems: Sequence[ValidationProblem]


class ProcedureNotSubscribableError(__BaseProcedureError):
    type: Literal["procedure-not-subscribable-error"] = "procedure-not-subscribable-error"


class ProcedureCancelledError(__BaseProcedureError):
    type: Literal["procedure-cancelled-error"] = "procedure-cancelled-error"


class ProcedureInternalError(__BaseProcedureError):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR

    type: Literal["procedure-internal-error"] = "procedure-internal-error"
    traceback: Sequence[str]


ProcedureError = (
    ProcedureComponentNotFoundError
    | ProcedureNotFoundError
    | ProcedureNotPermittedError
    | ProcedureInvalidArgumentsError
    | ProcedureNotSubscribableError
    | ProcedureCancelledError
    | ProcedureInternalError
)


class NotFoundError(Error):
    __error_status_code__: ClassVar[int] = HTTP_404_NOT_FOUND
    type: Literal["not-found-error"] = "not-found-error"


class NotRunningError(Error):
    __error_status_code__: ClassVar[int] = HTTP_404_NOT_FOUND
    type: Literal["not-running-error"] = "not-running-error"


class AlreadyExistsError(Error):
    __error_status_code__: ClassVar[int] = HTTP_409_CONFLICT
    type: Literal["already-exists-error"] = "already-exists-error"
    field: str


class NotAuthenticatedError(Error):
    __error_status_code__: ClassVar[int] = HTTP_401_UNAUTHORIZED
    type: Literal["not-authenticated-error"] = "not-authenticated-error"


class NotPermittedError(Error):
    __error_status_code__: ClassVar[int] = HTTP_403_FORBIDDEN
    type: Literal["not-permitted-error"] = "not-permitted-error"


class BadCredentialsError(Error):
    __error_status_code__: ClassVar[int] = HTTP_401_UNAUTHORIZED
    type: Literal["bad-credentials-error"] = "bad-credentials-error"


class AuthenticationDisabledError(Error):
    __error_status_code__: ClassVar[int] = HTTP_403_FORBIDDEN
    type: Literal["authentication-disabled-error"] = "authentication-disabled-error"


class ValidationFailedError(Error):
    __error_status_code__: ClassVar[int] = HTTP_422_UNPROCESSABLE_ENTITY
    type: Literal["validation-failed-error"] = "validation-failed-error"
    problems: Sequence[ValidationProblem]


class HTTPError(Error):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["http-error"] = "http-error"
    status: int


APIError = (
    NotFoundError
    | AlreadyExistsError
    | NotRunningError
    | NotAuthenticatedError
    | NotPermittedError
    | BadCredentialsError
    | AuthenticationDisabledError
    | ValidationFailedError
    | HTTPError
)


class DatabaseUnexpectedError(Error):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-unexpected-error"] = "database-unexpected-error"
    message: str


class DatabaseLoadError(Error):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST
    type: Literal["database-load-error"] = "database-load-error"
    message: str


class DatabaseInitError(Error):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-init-error"] = "database-init-error"
    message: str


DatabaseError = (
    AlreadyExistsError
    | NotFoundError
    | DatabaseUnexpectedError
    | DatabaseLoadError
    | DatabaseInitError
)


class Failure(Exception):
    def __init__(self, error: Error | Callable[[], Error]) -> None:
        if not util.lenient_isinstance(error, Error) and callable(error):
            error = error()

        self.error = error
        self.message = str(error.type)
