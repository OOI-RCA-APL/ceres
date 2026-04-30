import builtins
import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeAlias, dataclass_transform

import pydantic
import pydantic.dataclasses
from pydantic import (
    Field,
    ImportString,
    SerializeAsAny,
    ValidationError,
    computed_field,
    model_serializer,
)
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

from ceres.__internal__.utilities.undefined import Undefined
from ceres.address import Address, DynamicAddress
from ceres.data import DataObject, simplify
from ceres.data.object import construct

if TYPE_CHECKING:
    from fastapi.exceptions import RequestValidationError

__all__ = [
    "Error",
    "ExceptionInfo",
    "ValidationProblem",
]


@dataclass_transform(
    kw_only_default=True, field_specifiers=(dataclasses.field, dataclasses.Field, Field)
)
@pydantic.dataclasses.dataclass(slots=True, kw_only=True)
class Error(Exception):
    """Base class for structured, serializable error values returned across the API.

    Each `Error` carries a discriminator `type` string and may include extra fields with
    error-specific context. When serialized, an `__error__: True` marker is injected at the front
    of the payload so consumers can identify error responses without inspecting `type`.

    Subclasses may override `__error_status_code__` to control the HTTP status code used when the
    error is returned from an API endpoint.
    """

    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    """HTTP status code returned when this error is raised from an API endpoint."""

    @computed_field
    @property
    def __error__(self) -> Literal[True]:
        """Always `True`, included in serialized output to mark a payload as an error."""
        return True

    type: str
    """Discriminator string identifying the concrete error class."""

    @model_serializer(mode="wrap")
    def _serialize(self, inner: Callable[[Any], Any]) -> Any:
        result = inner(self)
        if isinstance(result, dict):
            # Place `__error__` first in the serialized output for easier identification by
            # downstream consumers.
            result.pop("__error__", None)
            result = {"__error__": True, **result}

        return result

    def __post_init__(self) -> None:
        Exception.__init__(self, self.type)

    def __init_subclass__(cls, slots: bool = True, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "__dataclass_fields__" not in cls.__dict__:
            pydantic.dataclasses.dataclass(cls, slots=slots, kw_only=True)


class ExceptionInfo(DataObject, slots=True):
    """Serializable snapshot of a Python exception, including notes and a formatted traceback."""

    type: str
    """Class name of the exception."""

    message: str
    """String form of the exception."""

    notes: list[str] | None = Field(
        default=None,
        exclude_if=lambda notes: notes is None,
    )
    """Any `__notes__` attached to the exception, or `None` if there are none."""

    traceback: list[str]
    """Lines of the formatted traceback, as produced by `traceback.format_exception()`."""


def trace(exception: BaseException) -> ExceptionInfo:
    """Capture a `BaseException` as a serializable `ExceptionInfo`.

    Args:
        exception: The exception to capture.

    Returns:
        An `ExceptionInfo` containing the exception's class name, message, notes, and
        formatted traceback.

    Raises:
        TypeError: If `exception` is not a `BaseException` instance.
    """
    if not isinstance(exception, BaseException):
        raise TypeError("Expected exception object.")

    notes = getattr(exception, "__notes__", None)
    # `__notes__` is technically meant to be a list of strings, defensively guard against other
    # types so a malformed attribute does not break serialization.
    if notes is not None and not isinstance(notes, list):
        notes = None

    from traceback import format_exception

    return construct(
        ExceptionInfo,
        type=type(exception).__name__,
        message=str(exception),
        notes=notes,
        traceback=format_exception(exception),
    )


class ValidationProblem(DataObject, slots=True):
    """A single problem reported by Pydantic validation, with a resolved location."""

    type: str
    """Pydantic error type string, such as `"value_error"` or `"missing"`."""

    location: list[str | int]
    """Path to the offending value within the validated data."""

    message: str
    """Human-readable description of the problem."""

    @classmethod
    def extract(
        cls,
        error: ValidationError | RequestValidationError,
        source: object = Undefined,
    ) -> list[ValidationProblem]:
        """Convert a Pydantic validation error into a list of `ValidationProblem`.

        When `source` is provided, the resolved location for each problem is rewritten to
        substitute list indexes with `"name: <name>"` segments whenever the indexed item is a dict
        containing a `name` field. This produces more meaningful locations for users editing a
        configuration document.

        Args:
            error: The Pydantic or FastAPI validation error to convert.
            source: The original source object that was validated. If omitted, location paths are
                returned as-is.

        Returns:
            A list of `ValidationProblem` instances, one per sub-error reported by Pydantic.
        """
        data = simplify(source) if source is not Undefined else Undefined
        problems: list[ValidationProblem] = []

        for suberror in error.errors():
            # Strip the `__root__` segment Pydantic uses for top-level errors, it is not useful in
            # user-facing locations.
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

                        # When walking into an item of a list, prefer a `name`-based segment over
                        # the raw index so the location is stable across reorderings.
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
                # Fall back to the raw Pydantic location if walking the source data fails for any
                # reason, the location is best-effort.
                location = default_location

            problems.append(
                ValidationProblem(
                    type=suberror["type"],
                    location=location,
                    message=suberror["msg"],
                )
            )

        return problems


class _ComponentError(Error, slots=True):
    """Internal base for component-related errors."""

    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR


class ComponentValidationError(_ComponentError, slots=True):
    """Raised when a component's configuration fails validation."""

    type: Literal["component-validation-error"] = "component-validation-error"
    address: Address
    """Address of the component whose configuration is invalid."""
    problems: list[ValidationProblem]
    """The validation problems that were detected."""


class ComponentInitExceptionError(_ComponentError, slots=True):
    """Raised when a component raises an unhandled exception during initialization."""

    type: Literal["component-init-exception-error"] = "component-init-exception-error"
    address: Address
    """Address of the component that failed to initialize."""
    exception: ExceptionInfo
    """Captured exception information."""


if TYPE_CHECKING:
    from ceres.component import Component
else:
    Component = Any


class ComponentReferenceInvalidError(_ComponentError, slots=True):
    """Raised when a component reference points to the wrong type of component."""

    type: Literal["component-reference-invalid-error"] = "component-reference-invalid-error"
    address: Address
    """Address of the component holding the invalid reference."""
    referenced: DynamicAddress | Component
    """The reference value that was found to be invalid."""
    expected: ImportString[builtins.type]
    """Component type that was expected at the referenced address."""
    actual: ImportString[builtins.type]
    """Component type that was actually found."""


# Pydantic dataclasses with forward references need to be rebuilt once `Component` is resolvable.
pydantic.dataclasses.rebuild_dataclass(ComponentReferenceInvalidError)  # type: ignore[reportArgumentType]


class ComponentJobInvalidError(_ComponentError, slots=True):
    """Raised when a component job is misconfigured."""

    type: Literal["component-job-invalid-error"] = "component-job-invalid-error"
    message: str
    """Description of why the job is invalid."""


class ComponentUnexpectedError(_ComponentError, slots=True):
    """Raised when a component fails for an unexpected reason."""

    type: Literal["component-unexpected-error"] = "component-unexpected-error"
    exception: ExceptionInfo
    """Captured exception information."""


class ComponentCombinedError(_ComponentError, slots=True):
    """Aggregates multiple component errors into a single error value."""

    type: Literal["component-combined-error"] = "component-combined-error"
    errors: list[ComponentError]
    """The combined sequence of errors."""


ComponentError: TypeAlias = (
    ComponentValidationError
    | ComponentInitExceptionError
    | ComponentReferenceInvalidError
    | ComponentJobInvalidError
    | ComponentUnexpectedError
    | ComponentCombinedError
)
"""Discriminated union of all component-related errors."""


class _ProcedureError(Error, slots=True):
    """Internal base for procedure-related errors."""

    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST


class ProcedureComponentNotFoundError(_ProcedureError, slots=True):
    """Raised when no component exists at the address a procedure call targeted."""

    type: Literal["procedure-component-not-found-error"] = "procedure-component-not-found-error"


class ProcedureNotFoundError(_ProcedureError, slots=True):
    """Raised when the requested procedure does not exist on the target component."""

    type: Literal["procedure-not-found-error"] = "procedure-not-found-error"


class ProcedureNotPermittedError(_ProcedureError, slots=True):
    """Raised when the caller is not allowed to invoke the requested procedure."""

    type: Literal["procedure-not-permitted-error"] = "procedure-not-permitted-error"


class ProcedureInvalidArgumentsError(_ProcedureError, slots=True):
    """Raised when arguments passed to a procedure fail validation."""

    type: Literal["procedure-invalid-arguments-error"] = "procedure-invalid-arguments-error"
    problems: list[ValidationProblem]
    """The validation problems with the supplied arguments."""


class ProcedureNotSubscribableError(_ProcedureError, slots=True):
    """Raised when a procedure that does not support subscription is subscribed to."""

    type: Literal["procedure-not-subscribable-error"] = "procedure-not-subscribable-error"


class ProcedureCancelledError(_ProcedureError, slots=True):
    """Raised when a procedure invocation is cancelled before completing."""

    type: Literal["procedure-cancelled-error"] = "procedure-cancelled-error"


class ProcedureInternalError(_ProcedureError, slots=True):
    """Raised when a procedure fails with an unhandled exception."""

    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR

    type: Literal["procedure-internal-error"] = "procedure-internal-error"
    exception: ExceptionInfo
    """Captured exception information."""


ProcedureError: TypeAlias = (
    ProcedureComponentNotFoundError
    | ProcedureNotFoundError
    | ProcedureNotPermittedError
    | ProcedureInvalidArgumentsError
    | ProcedureNotSubscribableError
    | ProcedureCancelledError
    | ProcedureInternalError
)
"""Discriminated union of all procedure-related errors."""


class _APIError(Error, slots=True):
    """Internal base for API-layer errors."""


class NotFoundError(_APIError, slots=True):
    """Raised when a requested resource does not exist."""

    __error_status_code__: ClassVar[int] = HTTP_404_NOT_FOUND
    type: Literal["not-found-error"] = "not-found-error"


class NotRunningError(_APIError, slots=True):
    """Raised when an operation requires a running component or engine that is not running."""

    __error_status_code__: ClassVar[int] = HTTP_404_NOT_FOUND
    type: Literal["not-running-error"] = "not-running-error"


class NotConnectedError(_APIError, slots=True):
    """Raised when an operation requires an established connection that is not present."""

    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST
    type: Literal["not-connected-error"] = "not-connected-error"
    message: str | None = None
    """Optional human-readable detail about the missing connection."""


class NotReachableError(_APIError, slots=True):
    """Raised when a remote target cannot be reached."""

    __error_status_code__: ClassVar[int] = HTTP_503_SERVICE_UNAVAILABLE
    type: Literal["not-reachable-error"] = "not-reachable-error"
    message: str | None = None
    """Optional human-readable detail about why the target is unreachable."""


class AlreadyExistsError(_APIError, slots=True):
    """Raised when creation fails because a record with the same key already exists."""

    __error_status_code__: ClassVar[int] = HTTP_409_CONFLICT
    type: Literal["already-exists-error"] = "already-exists-error"
    field: str
    """Name of the field that conflicted."""
    value: str | None = None
    """Conflicting value, if known."""


class IntegrityError(_APIError, slots=True):
    """Raised when a database integrity constraint is violated."""

    __error_status_code__: ClassVar[int] = HTTP_409_CONFLICT
    type: Literal["integrity-error"] = "integrity-error"


class NotAuthenticatedError(_APIError, slots=True):
    """Raised when an operation requires authentication and none was provided."""

    __error_status_code__: ClassVar[int] = HTTP_401_UNAUTHORIZED
    type: Literal["not-authenticated-error"] = "not-authenticated-error"


class NotPermittedError(_APIError, slots=True):
    """Raised when the authenticated user is not allowed to perform the requested action."""

    __error_status_code__: ClassVar[int] = HTTP_403_FORBIDDEN
    type: Literal["not-permitted-error"] = "not-permitted-error"


class BadCredentialsError(_APIError, slots=True):
    """Raised when supplied credentials are rejected during authentication."""

    __error_status_code__: ClassVar[int] = HTTP_401_UNAUTHORIZED
    type: Literal["bad-credentials-error"] = "bad-credentials-error"


class AuthenticationDisabledError(_APIError, slots=True):
    """Raised when an authentication-only feature is invoked while authentication is disabled."""

    __error_status_code__: ClassVar[int] = HTTP_403_FORBIDDEN
    type: Literal["authentication-disabled-error"] = "authentication-disabled-error"


class ValidationFailedError(_APIError, slots=True):
    """Raised when a request payload fails validation."""

    __error_status_code__: ClassVar[int] = HTTP_422_UNPROCESSABLE_CONTENT
    type: Literal["validation-failed-error"] = "validation-failed-error"
    problems: list[ValidationProblem]
    """The validation problems that were detected."""


class HTTPError(_APIError, slots=True):
    """Generic wrapper for an upstream HTTP error response."""

    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["http-error"] = "http-error"
    status: int
    """HTTP status code returned by the upstream service."""


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
"""Discriminated union of all API-layer errors."""


class DatabaseUnreachableError(Error, slots=True):
    """Raised when the database cannot be reached."""

    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-unreachable-error"] = "database-unreachable-error"
    reason: str
    """Reason why the database is unreachable."""


class DatabaseProgrammingError(Error, slots=True):
    """Raised when an invalid query is sent to the database, indicates a programming bug."""

    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-programming-error"] = "database-programming-error"
    exception: ExceptionInfo
    """Captured exception information from the underlying database driver."""


class DatabaseUnexpectedError(Error, slots=True):
    """Raised when the database fails for an unexpected reason."""

    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-unexpected-error"] = "database-unexpected-error"
    reason: str
    """Description of the unexpected failure."""


class DatabaseLoadError(Error, slots=True):
    """Raised when database configuration cannot be loaded."""

    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST
    type: Literal["database-load-error"] = "database-load-error"
    message: str
    """Description of the load failure."""


class DatabaseInitError(Error, slots=True):
    """Raised when the database fails to initialize."""

    __error_status_code__: ClassVar[int] = HTTP_500_INTERNAL_SERVER_ERROR
    type: Literal["database-init-error"] = "database-init-error"
    message: str
    """Description of the initialization failure."""


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
"""Discriminated union of all database-related errors."""


class _ConfigError(Error, slots=True):
    """Internal base for configuration loading errors."""

    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST


class ConfigInvalidSourceError(_ConfigError, slots=True):
    """Raised when the configured config source path or URL is invalid."""

    type: Literal["config-invalid-source-error"] = "config-invalid-source-error"
    message: str
    """Description of why the source is invalid."""


class ConfigReadError(_ConfigError, slots=True):
    """Raised when reading the configuration source fails."""

    type: Literal["config-read-error"] = "config-read-error"
    message: str
    """Description of the read failure."""


class ConfigParseErrorLocation(DataObject, slots=True):
    """Line and column of a configuration parse error."""

    line: int
    """1-based line number where the error occurred."""

    column: int
    """1-based column number where the error occurred."""


class ConfigParseError(_ConfigError, slots=True):
    """Raised when the configuration source cannot be parsed."""

    type: Literal["config-parse-error"] = "config-parse-error"
    message: str | None = None
    """Optional description of the parse failure."""
    location: ConfigParseErrorLocation | None = None
    """Optional source location of the parse failure."""


class ConfigValidationError(_ConfigError, slots=True):
    """Raised when configuration content fails validation."""

    type: Literal["config-validation-error"] = "config-validation-error"
    problems: list[ValidationProblem]
    """The validation problems that were detected."""


class ConfigCombinedError(_ConfigError, slots=True):
    """Aggregates multiple configuration errors into a single error value."""

    type: Literal["config-combined-error"] = "config-combined-error"
    errors: list[ConfigError]
    """The combined sequence of errors."""


ConfigError: TypeAlias = (
    ConfigInvalidSourceError
    | ConfigReadError
    | ConfigParseError
    | ConfigValidationError
    | DatabaseError
    | ComponentError
    | ConfigCombinedError
)
"""Discriminated union of all configuration-related errors."""


class _ReloadError(Error, slots=True):
    """Internal base for configuration reload errors."""

    __error_status_code__: ClassVar[int] = HTTP_400_BAD_REQUEST


class ReloadConfigPathUnsetError(_ReloadError, slots=True):
    """Raised when a reload is requested but no config path was configured at startup."""

    type: Literal["reload-config-path-not-set-error"] = "reload-config-path-not-set-error"


class ReloadConfigInvalidError(_ReloadError, slots=True):
    """Raised when a reload fails because the new configuration is invalid."""

    type: Literal["reload-config-invalid-error"] = "reload-config-invalid-error"
    error: SerializeAsAny[ConfigError]
    """The underlying configuration error that caused the reload to fail."""


ReloadError: TypeAlias = ReloadConfigPathUnsetError | ReloadConfigInvalidError
"""Discriminated union of all reload-related errors."""
