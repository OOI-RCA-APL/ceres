from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeAlias

from pydantic import ImportString, ValidationError, computed_field, model_serializer
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from ceres._internal import util
from ceres.address import Address, DynamicAddress
from ceres.data import DataObject, DeferBuild, ImmutableDataObject, simplify

if TYPE_CHECKING:
    from fastapi.exceptions import RequestValidationError


_UNDEFINED = object()


class ValidationProblem(ImmutableDataObject, DeferBuild):
    type: str
    location: Sequence[str | int]
    message: str

    @classmethod
    def extract(
        cls,
        error: ValidationError | RequestValidationError,
        source: object = _UNDEFINED,
    ) -> list[ValidationProblem]:
        data = simplify(source) if source is not _UNDEFINED else _UNDEFINED
        problems: list[ValidationProblem] = []

        for suberror in error.errors():
            default_location = list(segment for segment in suberror["loc"] if segment != "__root__")
            location: list[str | int] | None = []
            try:
                if source is not _UNDEFINED:
                    location = []
                    parent: object | None = None
                    current: Any = data
                    for segment in default_location:
                        if isinstance(current, dict):
                            current = current.get(segment)
                        elif isinstance(current, list):
                            current = current[int(segment)]

                        if (
                            isinstance(segment, int)
                            and isinstance(parent, list)
                            and isinstance(current, dict)
                            and "name" in current
                        ):
                            location.append(f"name: {current['name']}")
                        else:
                            location.append(segment)

                        parent = current
                else:
                    location = default_location
            except Exception:
                location = default_location

            problems.append(
                ValidationProblem(
                    type=suberror["type"],
                    location=location,
                    message=suberror["msg"],
                )
            )

        return problems


class Error(ImmutableDataObject):
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


class __BaseStandardError(Error, DeferBuild):
    pass


class __BaseComponentError(__BaseStandardError):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR


class ComponentValidationError(__BaseComponentError):
    type: Literal["component-validation-error"] = "component-validation-error"
    address: Address
    problems: Sequence[ValidationProblem]


class ComponentInitExceptionError(__BaseComponentError):
    type: Literal["component-init-exception-error"] = "component-init-exception-error"
    address: Address
    traceback: Sequence[str]


if TYPE_CHECKING:
    from ceres.component import Component
else:
    Component = Any


class ComponentReferenceInvalidError(__BaseComponentError):
    type: Literal["component-reference-invalid-error"] = "component-reference-invalid-error"
    address: Address
    referenced: DynamicAddress | Component
    expected: ImportString[type]
    actual: ImportString[type]


class ComponentJobInvalidError(__BaseComponentError):
    type: Literal["component-job-invalid-error"] = "component-job-invalid-error"
    message: str


class ComponentCombinedError(__BaseComponentError):
    type: Literal["component-combined-error"] = "component-combined-error"
    errors: Sequence[ComponentError]


ComponentError: TypeAlias = (
    ComponentValidationError
    | ComponentInitExceptionError
    | ComponentReferenceInvalidError
    | ComponentJobInvalidError
    | ComponentCombinedError
)


class __BaseProcedureError(__BaseStandardError):
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


ProcedureError: TypeAlias = (
    ProcedureComponentNotFoundError
    | ProcedureNotFoundError
    | ProcedureNotPermittedError
    | ProcedureInvalidArgumentsError
    | ProcedureNotSubscribableError
    | ProcedureCancelledError
    | ProcedureInternalError
)


class __BaseAPIError(__BaseStandardError):
    pass


class NotFoundError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_404_NOT_FOUND
    type: Literal["not-found-error"] = "not-found-error"


class NotRunningError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_404_NOT_FOUND
    type: Literal["not-running-error"] = "not-running-error"


class NotConnectedError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST
    type: Literal["not-connected-error"] = "not-connected-error"
    message: str | None = None


class NotReachableError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_503_SERVICE_UNAVAILABLE
    type: Literal["not-reachable-error"] = "not-reachable-error"
    message: str | None = None


class AlreadyExistsError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_409_CONFLICT
    type: Literal["already-exists-error"] = "already-exists-error"
    field: str
    value: str | None = None


class IntegrityError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_409_CONFLICT
    type: Literal["integrity-error"] = "integrity-error"


class NotAuthenticatedError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_401_UNAUTHORIZED
    type: Literal["not-authenticated-error"] = "not-authenticated-error"


class NotPermittedError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_403_FORBIDDEN
    type: Literal["not-permitted-error"] = "not-permitted-error"


class BadCredentialsError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_401_UNAUTHORIZED
    type: Literal["bad-credentials-error"] = "bad-credentials-error"


class AuthenticationDisabledError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_403_FORBIDDEN
    type: Literal["authentication-disabled-error"] = "authentication-disabled-error"


class ValidationFailedError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_422_UNPROCESSABLE_CONTENT
    type: Literal["validation-failed-error"] = "validation-failed-error"
    problems: Sequence[ValidationProblem]


class HTTPError(__BaseAPIError):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["http-error"] = "http-error"
    status: int


APIError: TypeAlias = (
    NotFoundError
    | NotRunningError
    | NotConnectedError
    | NotReachableError
    | AlreadyExistsError
    | IntegrityError
    | NotAuthenticatedError
    | NotPermittedError
    | BadCredentialsError
    | AuthenticationDisabledError
    | ValidationFailedError
    | HTTPError
)


class DatabaseUnreachableError(__BaseStandardError):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-unreachable-error"] = "database-unreachable-error"
    message: str


class DatabaseProgrammingError(__BaseStandardError):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-programming-error"] = "database-programming-error"
    message: str
    traceback: Sequence[str]


class DatabaseUnexpectedError(__BaseStandardError):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-unexpected-error"] = "database-unexpected-error"
    message: str


class DatabaseLoadError(__BaseStandardError):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST
    type: Literal["database-load-error"] = "database-load-error"
    message: str


class DatabaseInitError(__BaseStandardError):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-init-error"] = "database-init-error"
    message: str


DatabaseError: TypeAlias = (
    AlreadyExistsError
    | IntegrityError
    | NotFoundError
    | DatabaseUnreachableError
    | DatabaseProgrammingError
    | DatabaseUnexpectedError
    | DatabaseLoadError
    | DatabaseInitError
)


class __BaseConfigError(__BaseStandardError):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST


class ConfigInvalidSourceError(__BaseConfigError):
    type: Literal["config-invalid-source-error"] = "config-invalid-source-error"
    message: str


class ConfigReadError(__BaseConfigError):
    type: Literal["config-read-error"] = "config-read-error"
    message: str


class ConfigParseErrorLocation(DataObject, DeferBuild):
    line: int
    column: int


class ConfigParseError(__BaseConfigError):
    type: Literal["config-parse-error"] = "config-parse-error"
    message: str | None = None
    location: ConfigParseErrorLocation | None = None


class ConfigValidationError(__BaseConfigError):
    type: Literal["config-validation-error"] = "config-validation-error"
    problems: Sequence[ValidationProblem]


class ConfigCombinedError(__BaseConfigError):
    type: Literal["config-combined-error"] = "config-combined-error"
    errors: Sequence[ConfigError]


ConfigError: TypeAlias = (
    ConfigInvalidSourceError
    | ConfigReadError
    | ConfigParseError
    | ConfigValidationError
    | DatabaseError
    | ComponentError
    | ConfigCombinedError
)


class __BaseReloadError(__BaseStandardError):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST


class ReloadConfigPathUnsetError(__BaseReloadError):
    type: Literal["reload-config-path-not-set-error"] = "reload-config-path-not-set-error"


class ReloadConfigInvalidError(__BaseReloadError):
    type: Literal["reload-config-invalid-error"] = "reload-config-invalid-error"
    error: ConfigError


ReloadError: TypeAlias = ReloadConfigPathUnsetError | ReloadConfigInvalidError


class Failure(Exception):
    def __init__(self, error: Error | Callable[[], Error]) -> None:
        if not util.lenient_isinstance(error, Error) and callable(error):
            error = error()

        self.error = error
        self.message = str(error.type)
