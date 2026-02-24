from collections.abc import Callable
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
from ceres._internal.util import Undefined
from ceres.address import Address, DynamicAddress
from ceres.data import DataObject, simplify

if TYPE_CHECKING:
    from fastapi.exceptions import RequestValidationError


class ValidationProblem(DataObject, slots=True):
    type: str
    location: list[str | int]
    message: str

    @classmethod
    def extract(
        cls,
        error: ValidationError | RequestValidationError,
        source: object = Undefined,
    ) -> list[ValidationProblem]:
        data = simplify(source) if source is not Undefined else Undefined
        problems: list[ValidationProblem] = []

        for suberror in error.errors():
            default_location = list(segment for segment in suberror["loc"] if segment != "__root__")
            location: list[str | int] | None = []
            try:
                if source is not Undefined:
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


class Error(DataObject, slots=True):
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


class _ComponentError(Error, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR


class ComponentValidationError(_ComponentError, slots=True):
    type: Literal["component-validation-error"] = "component-validation-error"
    address: Address
    problems: list[ValidationProblem]


class ComponentInitExceptionError(_ComponentError, slots=True):
    type: Literal["component-init-exception-error"] = "component-init-exception-error"
    address: Address
    traceback: list[str]


if TYPE_CHECKING:
    from ceres.component import Component
else:
    Component = Any


class ComponentReferenceInvalidError(_ComponentError, slots=True):
    type: Literal["component-reference-invalid-error"] = "component-reference-invalid-error"
    address: Address
    referenced: DynamicAddress | Component
    expected: ImportString[type]
    actual: ImportString[type]


class ComponentJobInvalidError(_ComponentError, slots=True):
    type: Literal["component-job-invalid-error"] = "component-job-invalid-error"
    message: str


class ComponentCombinedError(_ComponentError, slots=True):
    type: Literal["component-combined-error"] = "component-combined-error"
    errors: list[ComponentError]


ComponentError: TypeAlias = (
    ComponentValidationError
    | ComponentInitExceptionError
    | ComponentReferenceInvalidError
    | ComponentJobInvalidError
    | ComponentCombinedError
)


class _ProcedureError(Error, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST


class ProcedureComponentNotFoundError(_ProcedureError, slots=True):
    type: Literal["procedure-component-not-found-error"] = "procedure-component-not-found-error"


class ProcedureNotFoundError(_ProcedureError, slots=True):
    type: Literal["procedure-not-found-error"] = "procedure-not-found-error"


class ProcedureNotPermittedError(_ProcedureError, slots=True):
    type: Literal["procedure-not-permitted-error"] = "procedure-not-permitted-error"


class ProcedureInvalidArgumentsError(_ProcedureError, slots=True):
    type: Literal["procedure-invalid-arguments-error"] = "procedure-invalid-arguments-error"
    problems: list[ValidationProblem]


class ProcedureNotSubscribableError(_ProcedureError, slots=True):
    type: Literal["procedure-not-subscribable-error"] = "procedure-not-subscribable-error"


class ProcedureCancelledError(_ProcedureError, slots=True):
    type: Literal["procedure-cancelled-error"] = "procedure-cancelled-error"


class ProcedureInternalError(_ProcedureError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR

    type: Literal["procedure-internal-error"] = "procedure-internal-error"
    traceback: list[str]


ProcedureError: TypeAlias = (
    ProcedureComponentNotFoundError
    | ProcedureNotFoundError
    | ProcedureNotPermittedError
    | ProcedureInvalidArgumentsError
    | ProcedureNotSubscribableError
    | ProcedureCancelledError
    | ProcedureInternalError
)


class _APIError(Error, slots=True):
    pass


class NotFoundError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_404_NOT_FOUND
    type: Literal["not-found-error"] = "not-found-error"


class NotRunningError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_404_NOT_FOUND
    type: Literal["not-running-error"] = "not-running-error"


class NotConnectedError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST
    type: Literal["not-connected-error"] = "not-connected-error"
    message: str | None = None


class NotReachableError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_503_SERVICE_UNAVAILABLE
    type: Literal["not-reachable-error"] = "not-reachable-error"
    message: str | None = None


class AlreadyExistsError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_409_CONFLICT
    type: Literal["already-exists-error"] = "already-exists-error"
    field: str
    value: str | None = None


class IntegrityError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_409_CONFLICT
    type: Literal["integrity-error"] = "integrity-error"


class NotAuthenticatedError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_401_UNAUTHORIZED
    type: Literal["not-authenticated-error"] = "not-authenticated-error"


class NotPermittedError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_403_FORBIDDEN
    type: Literal["not-permitted-error"] = "not-permitted-error"


class BadCredentialsError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_401_UNAUTHORIZED
    type: Literal["bad-credentials-error"] = "bad-credentials-error"


class AuthenticationDisabledError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_403_FORBIDDEN
    type: Literal["authentication-disabled-error"] = "authentication-disabled-error"


class ValidationFailedError(_APIError, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_422_UNPROCESSABLE_CONTENT
    type: Literal["validation-failed-error"] = "validation-failed-error"
    problems: list[ValidationProblem]


class HTTPError(_APIError, slots=True):
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


class DatabaseUnreachableError(Error, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-unreachable-error"] = "database-unreachable-error"
    message: str


class DatabaseProgrammingError(Error, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-programming-error"] = "database-programming-error"
    message: str
    traceback: list[str]


class DatabaseUnexpectedError(Error, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-unexpected-error"] = "database-unexpected-error"
    message: str


class DatabaseLoadError(Error, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST
    type: Literal["database-load-error"] = "database-load-error"
    message: str


class DatabaseInitError(Error, slots=True):
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


class _ConfigError(Error, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST


class ConfigInvalidSourceError(_ConfigError, slots=True):
    type: Literal["config-invalid-source-error"] = "config-invalid-source-error"
    message: str


class ConfigReadError(_ConfigError, slots=True):
    type: Literal["config-read-error"] = "config-read-error"
    message: str


class ConfigParseErrorLocation(DataObject, slots=True):
    line: int
    column: int


class ConfigParseError(_ConfigError, slots=True):
    type: Literal["config-parse-error"] = "config-parse-error"
    message: str | None = None
    location: ConfigParseErrorLocation | None = None


class ConfigValidationError(_ConfigError, slots=True):
    type: Literal["config-validation-error"] = "config-validation-error"
    problems: list[ValidationProblem]


class ConfigCombinedError(_ConfigError, slots=True):
    type: Literal["config-combined-error"] = "config-combined-error"
    errors: list[ConfigError]


ConfigError: TypeAlias = (
    ConfigInvalidSourceError
    | ConfigReadError
    | ConfigParseError
    | ConfigValidationError
    | DatabaseError
    | ComponentError
    | ConfigCombinedError
)


class _ReloadError(Error, slots=True):
    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST


class ReloadConfigPathUnsetError(_ReloadError, slots=True):
    type: Literal["reload-config-path-not-set-error"] = "reload-config-path-not-set-error"


class ReloadConfigInvalidError(_ReloadError, slots=True):
    type: Literal["reload-config-invalid-error"] = "reload-config-invalid-error"
    error: ConfigError


ReloadError: TypeAlias = ReloadConfigPathUnsetError | ReloadConfigInvalidError


class Failure(Exception):
    def __init__(self, error: Error | Callable[[], Error]) -> None:
        if not util.lenient_isinstance(error, Error) and callable(error):
            error = error()

        self.error = error
        self.message = str(error.type)
