import inspect
import traceback
from copy import copy
from functools import wraps
from inspect import Parameter
from types import NoneType, UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    List,
    Mapping,
    Optional,
    Type,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

import click
import click.shell_completion
import rich
from click import ClickException, Context
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from typer import Argument, Option, Typer
from typer.main import lenient_issubclass
from typer.models import ArgumentInfo, OptionInfo
from typing_extensions import TypedDict, Unpack

from ceres.data import ImmutableDataObject, jsonify
from ceres.errors import Failure
from ceres.internal.utilities import (
    get_args_model,
    get_unannotated_type,
    lenient_isinstance,
    syncify,
)


class CLIRouter(Typer):
    def __init__(self, *, name: str, help: str | None = None):
        super().__init__(
            name=name,
            help=help,
            add_completion=False,
            no_args_is_help=True,
            rich_markup_mode="markdown",
        )

    if not TYPE_CHECKING:

        @wraps(Typer.command)
        def command(self, *args, **kwargs):
            base = super()

            def decorator(function):
                base.command(*args, **kwargs)(_enhance_cli_command(function))
                return function

            return decorator

        @wraps(Typer.callback)
        def callback(self, *args, **kwargs):
            base = super()

            def decorator(function):
                base.callback(*args, **kwargs)(syncify(function))
                return function

            return decorator


CLIContext = Context


class BaseParametersModel(ImmutableDataObject):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")


def _enhance_cli_command(function: Any) -> Any:
    signature = inspect.signature(function)
    fields_to_groups: dict[str, str] = {}
    parameters: list[Parameter] = []
    parameters_model = get_args_model(function, model_base=BaseParametersModel)

    try:
        for parameter_name, parameter in signature.parameters.items():
            option_group = _get_parameter_metadata(parameter, CLIOptionGroupInfo)
            if option_group is not None:
                group_name = parameter_name
                group_cls: BaseModel = get_unannotated_type(parameter.annotation)
                if not lenient_issubclass(group_cls, BaseModel):
                    raise TypeError(
                        f"Option group annotation `{group_name}` must be a subclass of `BaseModel`."
                    )
                for field_name in group_cls.model_fields.keys():
                    fields_to_groups[field_name] = group_name
                for field_name, field in group_cls.model_fields.items():
                    parameters.append(_get_typer_compatible_parameter(field, field_name))
                continue

            field = parameters_model.model_fields[parameter_name]
            parameters.append(_get_typer_compatible_parameter(field, parameter_name))

        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any):
            applied_kwargs: dict[str, Any] = {}
            for key, value in kwargs.items():
                if key not in fields_to_groups:
                    applied_kwargs[key] = value
                    continue

                field_name = key
                group_name = fields_to_groups[key]
                if group_name not in applied_kwargs:
                    applied_kwargs[group_name] = {}

                applied_kwargs[group_name][field_name] = value

            try:
                parsed = parameters_model.model_validate(applied_kwargs)
            except ValidationError as error:
                raise CLICommandFailed(_format_errors(error, fields_to_groups))

            try:
                result = syncify(function)(*args, **parsed.__dict__)
            except Failure as failure:
                raise CLICommandFailed(jsonify(failure.error, indent=2))

            if result is not None:
                try:
                    rich.print(jsonify(result, indent=2))
                except Exception:
                    pass

            return result

        wrapped.__signature__ = signature.replace(parameters=parameters)  # type: ignore
        return wrapped
    except Exception:
        traceback.print_exc()


class CLIOptionGroupInfo:
    pass


class CLIParameterArgs(TypedDict, total=False):
    # ParameterInfo
    # param_decls: Optional[Sequence[str]]
    callback: Optional[Callable[..., Any]]
    metavar: Optional[str]
    expose_value: bool
    is_eager: bool
    envvar: Optional[Union[str, List[str]]]
    autocompletion: Optional[Callable[..., Any]]
    default_factory: Optional[Callable[[], Any]]
    # Custom type
    parser: Optional[Callable[[str], Any]]
    click_type: Optional[click.ParamType]
    # Option
    show_default: bool
    help: Optional[str]
    hidden: bool
    show_choices: bool
    show_envvar: bool
    # Choice
    case_sensitive: bool
    # Numbers
    min: Optional[Union[int, float]]
    max: Optional[Union[int, float]]
    clamp: bool
    # DateTime
    formats: Optional[list[str]]
    # File
    mode: Optional[str]
    encoding: Optional[str]
    errors: Optional[str]
    lazy: Optional[bool]
    atomic: bool
    # Path
    exists: bool
    file_okay: bool
    dir_okay: bool
    writable: bool
    readable: bool
    resolve_path: bool
    allow_dash: bool
    path_type: Union[None, Type[str], Type[bytes]]
    # Rich settings
    rich_help_panel: Union[str, None]


class CLIArgumentArgs(CLIParameterArgs, total=False):
    pass


class CLIOptionArgs(CLIParameterArgs, total=False):
    prompt: Union[bool, str]
    prompt_required: bool
    confirmation_prompt: bool
    hide_input: bool
    is_flag: Optional[bool]
    flag_value: Optional[Any]
    count: bool
    allow_from_autoenv: bool


def CLIArgument(
    type: type[Any] | Any,
    **kwargs: Unpack[CLIArgumentArgs],
) -> Any:
    argument = Argument(..., **kwargs)  # type: ignore
    argument.type = _get_typer_compatible_type(type)
    return argument


def CLIOption(
    type: type[Any] | Any,
    *decls: str,
    **kwargs: Unpack[CLIOptionArgs],
) -> Any:
    option = Option(..., *decls, **kwargs)  # type: ignore
    option.type = _get_typer_compatible_type(type)
    return option


def CLIOptionGroup() -> Any:
    return CLIOptionGroupInfo()


def _get_typer_compatible_type(type: type[Any] | Any) -> type[Any] | Any:
    if get_origin(type) is UnionType:
        args = get_args(type)
        if any(current is NoneType for current in args):
            other = tuple(current for current in args if current is not NoneType)
            if len(other) == 1:
                return Optional[other[0]]  # type: ignore

            return Optional[Union[other]]  # type: ignore

    return type


_VirtualDefault = (
    ArgumentInfo | OptionInfo | FieldInfo | type(PydanticUndefined) | type(Parameter.empty)
)

_T = TypeVar("_T")


def _get_parameter_metadata(parameter: inspect.Parameter, metadata_type: type[_T]) -> _T | None:
    if lenient_issubclass(parameter.default, metadata_type):
        return parameter.default

    if parameter.annotation is inspect.Parameter.empty:
        return None

    metadata = getattr(parameter.annotation, "__metadata__", None)
    if metadata is None:
        return None

    for item in metadata:
        if lenient_isinstance(item, metadata_type):
            return item

    return None


def _get_typer_parameter(field: FieldInfo, parameter_type: type[_T]) -> _T | None:
    if lenient_isinstance(field.default, parameter_type):
        return field.default

    for item in field.metadata:
        if lenient_isinstance(item, parameter_type):
            return item

    return None


def _create_typer_argument(field: FieldInfo) -> ArgumentInfo | None:
    argument = _get_typer_parameter(field, ArgumentInfo)
    if argument is None:
        return None

    argument = copy(argument)

    if argument.help is None:
        argument.help = field.description
    if isinstance(field.default, _VirtualDefault):
        argument.default = ...
        argument.show_default = False
    if field.default_factory is not None:
        argument.default_factory = field.default_factory

    return argument


def _create_typer_option(field: FieldInfo) -> OptionInfo:
    option = _get_typer_parameter(field, OptionInfo)
    if option is not None:
        option = copy(option)
    else:
        option = Option()

    if option.help is None:
        option.help = field.description
    if isinstance(field.default, _VirtualDefault):
        option.default = ...
        option.show_default = False
    if field.default_factory is not None:
        option.default_factory = field.default_factory

    return option


def _get_typer_compatible_parameter(field: FieldInfo, name: str) -> Parameter:
    meta = _create_typer_argument(field) or _create_typer_option(field)
    default = field.default if field.default is not PydanticUndefined else Parameter.empty
    if lenient_isinstance(default, _VirtualDefault):
        default = Parameter.empty

    annotation: Any = None
    if hasattr(meta, "type"):
        annotation = getattr(meta, "type")
    if annotation is None:
        annotation = field.annotation

    annotation = Annotated[annotation, meta]

    return Parameter(
        name=name,
        default=default,
        kind=inspect.Parameter.KEYWORD_ONLY,
        annotation=annotation,
    )


def _format_errors(error: ValidationError, fields: Mapping[str, str]) -> str:
    lines: list[str] = []
    for suberror in error.errors():
        if len(suberror["loc"]) > 1 and suberror["loc"][1] in fields:
            suberror["loc"] = suberror["loc"][1:]
        path = "/".join(str(segment) for segment in suberror["loc"])
        lines.append(f"- {path}: {suberror['msg']}")

    return "\n".join(lines)


class CLICommandFailed(ClickException):
    pass
