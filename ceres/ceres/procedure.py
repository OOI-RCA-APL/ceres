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
    TypeVar,
    get_type_hints,
)

from pydantic import schema_of, validate_arguments
from pydantic.typing import get_args

from .data import ImmutableDataObject, Name, PositiveTimeDelta
from .internal.binding import Binding, add_binding
from .internal.utilities import get_member_name, is_optional, strify


class ProcedureKind(str, Enum):
    QUERY = "query"
    ACTION = "action"


class ProcedureSchemas(ImmutableDataObject):
    input: Mapping[str, Any] | None
    output: Mapping[str, Any]


class ProcedureInputInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]
    required: bool
    default: object | None


class ProcedureOutputInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]


class BaseProcedureBinding(Binding):
    kind: ProcedureKind
    name: str
    function: str
    live: bool
    input: ProcedureInputInfo | None
    output: ProcedureOutputInfo


class QueryBinding(BaseProcedureBinding):
    kind: Literal[ProcedureKind.QUERY] = ProcedureKind.QUERY
    poll: PositiveTimeDelta


class ActionBinding(BaseProcedureBinding):
    kind: Literal[ProcedureKind.ACTION] = ProcedureKind.ACTION


ProcedureBinding = QueryBinding | ActionBinding


def _get_schema(hint: Any) -> Mapping[str, Any]:
    schema = schema_of(hint)

    if schema.get("type") == "null":
        schema = {"title": "Null", "type": "null"}
    elif "definitions" in schema and schema["definitions"]:
        schema = list(schema["definitions"].values())[0]

    title = schema.get("title")
    if title is not None:
        if title.startswith("ParsingModel[") and title.endswith("]"):
            title = title[len("ParsingModel[") : -1]

        schema["title"] = title

    return schema


class _ValidatedProcedureInfo(ImmutableDataObject):
    input: ProcedureInputInfo | None
    output: ProcedureOutputInfo
    live: bool


def _validate_procedure(
    function: Callable[..., Any],
    kind: ProcedureKind,
) -> _ValidatedProcedureInfo:
    signature = inspect.signature(function)
    parameters = [*signature.parameters.values()]
    if len(parameters) not in (1, 2) or any(
        parameter.kind not in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.POSITIONAL_ONLY)
        for parameter in parameters
    ):
        raise ValueError(
            f"{kind} {strify(function)} must have exactly one or two positional parameters, 'self', and optionally, an input parameter"
        )

    hints = get_type_hints(function)

    if len(parameters) < 2:
        input_info: ProcedureInputInfo | None = None
    else:
        input_json_schema: Mapping[str, Any] | None = None

        input_parameter = parameters[1]
        if input_parameter.name not in hints:
            raise ValueError(
                f"second positional parameter '{input_parameter.name}' of {kind} {strify(function)} must have a type hint"
            )

        input_hint = hints[input_parameter.name]

        try:
            input_json_schema = _get_schema(input_hint)
        except Exception:
            raise ValueError(
                f"second positional parameter '{input_parameter.name}' of {kind} {strify(function)} must be parseable as a JSON object"
            )

        if input_parameter.default is Parameter.empty:
            input_required = not is_optional(input_hint)
            input_default: object | None = None
        else:
            input_required = False
            # TODO: Check that the default input is valid.
            input_default = input_parameter.default

        input_info = ProcedureInputInfo(
            json_schema=input_json_schema,
            required=input_required,
            default=input_default,
        )

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
        output_json_schema = _get_schema(output_hint)
    except Exception:
        raise ValueError(
            f"output type of {kind} {strify(function)} must be serializable as a JSON object"
        )

    output_info = ProcedureOutputInfo(
        json_schema=output_json_schema,
    )

    return _ValidatedProcedureInfo(
        input=input_info,
        output=output_info,
        live=live,
    )


_ProcedureFunctionT = TypeVar(
    "_ProcedureFunctionT",
    bound=Callable[[Any], Awaitable[Any] | AsyncIterable[Any]]
    | Callable[[Any, Any], Awaitable[Any] | AsyncIterable[Any]],
)


@validate_arguments
def query(
    name: Name,
    *,
    poll: float | timedelta = timedelta(seconds=5),
) -> Callable[[_ProcedureFunctionT], _ProcedureFunctionT]:
    def bind(function: _ProcedureFunctionT) -> _ProcedureFunctionT:
        validated = _validate_procedure(function, ProcedureKind.QUERY)
        add_binding(
            function,
            QueryBinding(
                name=name,
                function=get_member_name(function),
                input=validated.input,
                output=validated.output,
                live=validated.live,
                poll=poll if isinstance(poll, timedelta) else timedelta(seconds=poll),
            ),
        )

        return function

    return bind


@validate_arguments
def action(name: Name) -> Callable[[_ProcedureFunctionT], _ProcedureFunctionT]:
    def bind(function: _ProcedureFunctionT) -> _ProcedureFunctionT:
        validated = _validate_procedure(function, ProcedureKind.ACTION)
        add_binding(
            function,
            ActionBinding(
                name=name,
                function=get_member_name(function),
                input=validated.input,
                output=validated.output,
                live=validated.live,
            ),
        )

        return function

    return bind
