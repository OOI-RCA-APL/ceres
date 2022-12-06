import inspect
import traceback
from enum import Enum
from functools import wraps
from inspect import Parameter
from typing import (
    Any,
    AsyncIterable,
    Callable,
    Literal,
    Mapping,
    TypeVar,
    get_type_hints,
)

from pydantic import schema_of

from .data import ImmutableDataObject
from .internal.binding import Binding, add_binding
from .internal.utilities import strify
from .schedule import Schedule


class ProcedureKind(str, Enum):
    QUERY = "query"
    ACTION = "action"
    JOB = "job"
    SUBSCRIPTION = "subscription"
    DISPLAY = "display"

    def try_cast(self, /, enum_cls: type[Enum]) -> "CallableProcedureKind | None":
        try:
            return enum_cls(self.value)
        except Exception:
            return None


class CallableProcedureKind(str, Enum):
    QUERY = "query"
    ACTION = "action"
    JOB = "job"

    def upcast(self) -> "ProcedureKind":
        return ProcedureKind(self.value)


class SubscribableProcedureKind(str, Enum):
    SUBSCRIPTION = "subscription"
    DISPLAY = "display"

    def upcast(self) -> "ProcedureKind":
        return ProcedureKind(self.value)


class ProcedureSchemas(ImmutableDataObject):
    input: Mapping[str, Any] | None
    output: Mapping[str, Any]


class BaseProcedureBinding(Binding):
    kind: ProcedureKind
    name: str
    function: str
    schemas: ProcedureSchemas


class QueryBinding(BaseProcedureBinding):
    kind: Literal[ProcedureKind.QUERY] = ProcedureKind.QUERY


class ActionBinding(BaseProcedureBinding):
    kind: Literal[ProcedureKind.ACTION] = ProcedureKind.ACTION


class JobBinding(BaseProcedureBinding):
    kind: Literal[ProcedureKind.JOB] = ProcedureKind.JOB
    default_schedule: Schedule | None = None
    default_input: object | None = None


class SubscriptionBinding(BaseProcedureBinding):
    kind: Literal[ProcedureKind.SUBSCRIPTION] = ProcedureKind.SUBSCRIPTION


class DisplayBinding(BaseProcedureBinding):
    kind: Literal[ProcedureKind.DISPLAY] = ProcedureKind.DISPLAY


ProcedureBinding = QueryBinding | ActionBinding | JobBinding | SubscriptionBinding | DisplayBinding


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


def _validate_procedure(
    function: Callable[..., Any],
    kind: ProcedureKind,
) -> ProcedureSchemas:
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

    if len(parameters) == 1:
        input_schema: Mapping[str, Any] | None = None
    else:
        input_parameter = parameters[1]
        if input_parameter.name not in hints:
            raise ValueError(
                f"second positional parameter '{input_parameter.name}' of {kind} {strify(function)} must have a type hint"
            )

        input_hint = hints[input_parameter.name]
        try:
            input_schema = _get_schema(input_hint)
        except Exception:
            raise ValueError(
                f"second positional parameter '{input_parameter.name}' of {kind} {strify(function)} must be parseable as a JSON object"
            )

    if "return" not in hints:
        raise ValueError(f"return type of {kind} {strify(function)} must be specified")

    output_hint = hints["return"]

    if kind.try_cast(SubscribableProcedureKind):
        error = ValueError(f"return type of {kind} {strify(function)} must be AsyncIterable[T]")
        if output_hint.__name__ != "AsyncIterable":
            raise error

        try:
            output_hint = output_hint.__args__[0]  # type: ignore
        except Exception:
            traceback.print_exc()
            raise error

    try:
        output_schema = _get_schema(output_hint)
    except Exception:
        raise ValueError(
            f"return type of {kind} {strify(function)} must be serializable as a JSON object"
        )

    return ProcedureSchemas(
        input=input_schema,
        output=output_schema,
    )


_CallableProcedureFunctionT = TypeVar(
    "_CallableProcedureFunctionT",
    bound=Callable[[Any], Any] | Callable[[Any, Any], Any],
)


def query(name: str) -> Callable[[_CallableProcedureFunctionT], _CallableProcedureFunctionT]:
    def bind(function: _CallableProcedureFunctionT) -> _CallableProcedureFunctionT:
        schemas = _validate_procedure(function, ProcedureKind.QUERY)
        add_binding(
            function,
            QueryBinding(
                name=name,
                function=function.__name__,
                schemas=schemas,
            ),
        )

        return function

    return bind


def action(name: str) -> Callable[[_CallableProcedureFunctionT], _CallableProcedureFunctionT]:
    def bind(function: _CallableProcedureFunctionT) -> _CallableProcedureFunctionT:
        schemas = _validate_procedure(function, ProcedureKind.ACTION)
        add_binding(
            function,
            ActionBinding(
                name=name,
                function=function.__name__,
                schemas=schemas,
            ),
        )

        return function

    return bind


def job(
    name: str,
    *,
    default_schedule: Schedule | None = None,
    default_input: object | None = None,
) -> Callable[[_CallableProcedureFunctionT], _CallableProcedureFunctionT]:
    def bind(function: _CallableProcedureFunctionT) -> _CallableProcedureFunctionT:
        parameters = inspect.signature(function).parameters
        if len(parameters) == 1 and default_input is not None:
            raise ValueError("job does not take any input, but a default input has been specified")

        schemas = _validate_procedure(function, ProcedureKind.JOB)
        add_binding(
            function,
            JobBinding(
                name=name,
                function=function.__name__,
                schemas=schemas,
                default_schedule=default_schedule,
                default_input=default_input,
            ),
        )

        return function

    return bind


_SubscribableProcedureFunctionT = TypeVar(
    "_SubscribableProcedureFunctionT",
    bound=Callable[[Any], AsyncIterable[Any]] | Callable[[Any, Any], AsyncIterable[Any]],
)


def subscription(
    name: str,
    *,
    dedupe: bool = False,
) -> Callable[[_SubscribableProcedureFunctionT], _SubscribableProcedureFunctionT]:
    def bind(function: _SubscribableProcedureFunctionT) -> _SubscribableProcedureFunctionT:
        schemas = _validate_procedure(function, ProcedureKind.SUBSCRIPTION)
        add_binding(
            function,
            SubscriptionBinding(
                name=name,
                function=function.__name__,
                schemas=schemas,
            ),
        )

        if dedupe:
            function = _dedupe(function)

        return function

    return bind


def display(
    name: str,
    *,
    dedupe: bool = False,
) -> Callable[[_SubscribableProcedureFunctionT], _SubscribableProcedureFunctionT]:
    def bind(function: _SubscribableProcedureFunctionT) -> _SubscribableProcedureFunctionT:
        schemas = _validate_procedure(function, ProcedureKind.SUBSCRIPTION)
        add_binding(
            function,
            DisplayBinding(
                name=name,
                function=function.__name__,
                schemas=schemas,
            ),
        )

        if dedupe:
            function = _dedupe(function)

        return function

    return bind


def _dedupe(function: _SubscribableProcedureFunctionT) -> _SubscribableProcedureFunctionT:
    @wraps(function)
    async def wrapper(*args: object, **kwargs: object) -> AsyncIterable[object | None]:
        yielded = False
        previous: object = None

        async for value in function(*args, **kwargs):
            if not yielded or value != previous:
                yielded = True
                yield value
                previous = value

    return wrapper  # type: ignore
