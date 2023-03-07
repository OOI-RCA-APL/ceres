import inspect
from datetime import timedelta
from enum import Enum
from inspect import Parameter
from typing import (
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Literal,
    Mapping,
    ParamSpec,
    TypeVar,
    get_type_hints,
    overload,
)

from pydantic import BaseModel, ConfigDict, Extra, schema_of, validate_arguments
from pydantic.decorator import ValidatedFunction
from pydantic.typing import get_args

from ceres.data import ImmutableDataObject, Name, PositiveTimeDelta
from ceres.internal.binding import add_local_binding
from ceres.internal.utilities import get_function_name, strify


class ProcedureKind(str, Enum):
    QUERY = "query"
    ACTION = "action"


class ProcedureSchemas(ImmutableDataObject):
    args: Mapping[str, Any] | None
    output: Mapping[str, Any]


class ProcedureArgsInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]
    required: bool


class ProcedureOutputInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]


class _ProcedureBinding(ImmutableDataObject):
    name: str
    kind: ProcedureKind
    function: str
    live: bool
    args: ProcedureArgsInfo | None
    output: ProcedureOutputInfo


class QueryBinding(_ProcedureBinding):
    kind: Literal[ProcedureKind.QUERY] = ProcedureKind.QUERY
    poll: PositiveTimeDelta


class ActionBinding(_ProcedureBinding):
    kind: Literal[ProcedureKind.ACTION] = ProcedureKind.ACTION


ProcedureBinding = QueryBinding | ActionBinding


_P = ParamSpec("_P")
_T = TypeVar("_T", bound=Awaitable[Any] | AsyncIterable[Any])


@overload
def query(function: Callable[_P, _T]) -> Callable[_P, _T]:
    ...


@overload
def query(
    *,
    name: Name,
    poll: float | timedelta = ...,
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    ...


@validate_arguments
def query(
    function: Callable[_P, _T] | None = None,
    *,
    name: Name | None = None,
    poll: float | timedelta = timedelta(seconds=5),
) -> Callable[_P, _T] | Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def bind(function: Callable[_P, _T]) -> Callable[_P, _T]:
        validated = _validate_procedure(function, ProcedureKind.QUERY)
        add_local_binding(
            function,
            QueryBinding(
                name=_normalize_procedure_name(name) if name else _get_procedure_name(function),
                function=get_function_name(function),
                args=validated.args,
                output=validated.output,
                live=validated.live,
                poll=poll if isinstance(poll, timedelta) else timedelta(seconds=poll),
            ),
        )

        return function

    if function is None:
        return bind

    return bind(function)


@overload
def action(function: Callable[_P, _T]) -> Callable[_P, _T]:
    ...


@overload
def action(*, name: Name) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    ...


@validate_arguments
def action(
    function: Callable[_P, _T] | None = None,
    *,
    name: Name | None = None,
) -> Callable[_P, _T] | Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def bind(function: Callable[_P, _T]) -> Callable[_P, _T]:
        validated = _validate_procedure(function, ProcedureKind.ACTION)
        add_local_binding(
            function,
            ActionBinding(
                name=_normalize_procedure_name(name) if name else _get_procedure_name(function),
                function=get_function_name(function),
                args=validated.args,
                output=validated.output,
                live=validated.live,
            ),
        )

        return function

    if function is None:
        return bind

    return bind(function)


def _normalize_procedure_name(name: str) -> Name:
    return name.replace("_", "-").strip().strip("-")


def _get_procedure_name(callable: Callable[..., Any]) -> Name:
    return _normalize_procedure_name(get_function_name(callable))


def _get_args_schema(model: type[BaseModel]) -> Mapping[str, Any]:
    schema = schema_of(model)

    definitions = schema.get("definitions")
    if not isinstance(definitions, dict) or not definitions:
        return schema

    root = list(definitions.values())[0]
    if not isinstance(root, dict):
        return schema

    properties = root.get("properties")
    if isinstance(properties, dict):
        properties.pop("self", None)
        properties.pop("v__duplicate_kwargs", None)

        args_property = properties.get("args")
        if isinstance(args_property, dict):
            if not args_property.get("items"):
                del properties["args"]

        kwargs_property = properties.get("kwargs")
        if isinstance(kwargs_property, dict):
            if not kwargs_property.get("items"):
                del properties["kwargs"]

    required = root.get("required")
    if isinstance(required, list):
        if "self" in required:
            required.remove("self")
        if not required:
            del root["required"]

    return schema


def _get_output_schema(hint: Any) -> Mapping[str, Any]:
    return schema_of(hint)


class _ValidatedProcedureInfo(ImmutableDataObject):
    args: ProcedureArgsInfo | None
    output: ProcedureOutputInfo
    live: bool


def _validate_procedure(
    function: Callable[..., Any],
    kind: ProcedureKind,
) -> _ValidatedProcedureInfo:
    signature = inspect.signature(function)
    parameters = [*signature.parameters.values()]
    if not parameters or parameters[0].name != "self":
        raise ValueError(f"{kind} {strify(function)} must have 'self' as its first parameter")
    if any(parameter.kind == Parameter.POSITIONAL_ONLY for parameter in parameters[1:]):
        raise ValueError(f"{kind} {strify(function)} cannot have positional-only arguments")

    validation_config: Any = ConfigDict(extra=Extra.forbid)
    validated = ValidatedFunction(function, validation_config)
    args_model = validated.model
    args_json_schema = _get_args_schema(args_model)
    args_info = ProcedureArgsInfo(
        json_schema=args_json_schema,
        required=any(
            field.required and not field.name == "self" for field in args_model.__fields__.values()
        ),
    )

    hints = get_type_hints(function)
    if "return" not in hints:
        raise ValueError(f"return type of {kind} {strify(function)} must be specified")

    output_hint = hints["return"]

    live = inspect.isasyncgenfunction(function)

    if live:
        error = ValueError(
            f"return type of live {kind} {strify(function)} must be AsyncIterable[T]"
        )

        try:
            if output_hint.__name__ != "AsyncIterable":
                raise error

            output_hint = get_args(output_hint)[0]
        except Exception:
            raise error

    try:
        output_json_schema = _get_output_schema(output_hint)
    except Exception:
        raise ValueError(
            f"output type of {kind} {strify(function)} must be serializable as a JSON object"
        )

    output_info = ProcedureOutputInfo(
        json_schema=output_json_schema,
    )

    return _ValidatedProcedureInfo(
        args=args_info,
        output=output_info,
        live=live,
    )
