from collections.abc import Callable
from typing import TYPE_CHECKING, Any, get_type_hints, overload

if TYPE_CHECKING:
    from pydantic import BaseModel, ConfigDict
    from pydantic._internal._validate_call import ValidateCallWrapper
else:
    ValidateCallWrapper = object

_DEFAULT_VALIDATED_FUNCTION_CONFIG: ConfigDict = {
    "arbitrary_types_allowed": True,
    "populate_by_name": True,
    "extra": "forbid",
}


def create_validated_function(
    function: Callable[..., Any],
    /,
    *,
    config: ConfigDict | None = None,
    validate_return: bool = False,
) -> ValidateCallWrapper:
    """Wrap ``function`` with Pydantic runtime argument validation.

    Args:
        function: The callable to validate.
        config: Optional Pydantic ``ConfigDict`` overrides merged with the default config.
        validate_return: When ``True``, also validate the return value.

    Returns:
        A ``ValidateCallWrapper`` that validates arguments before calling the original function.
    """
    config = {
        **_DEFAULT_VALIDATED_FUNCTION_CONFIG,
        **(config or {}),
    }
    from pydantic import validate_call

    return validate_call(config=config, validate_return=validate_return)(function)  # type: ignore


@overload
def validated_function[T: Callable[..., Any]](
    *,
    config: ConfigDict | None = None,
    validate_return: bool = False,
) -> Callable[[T], T]: ...


@overload
def validated_function[T: Callable[..., Any]](function: T, /) -> T: ...


def validated_function[T: Callable[..., Any]](
    function: T | None = None,
    /,
    *,
    config: ConfigDict | None = None,
    validate_return: bool = False,
) -> T | Callable[[T], T]:
    """Decorate a function with Pydantic runtime argument validation.

    Can be used as a bare decorator (``@validated_function``) or called with keyword arguments
    (``@validated_function(validate_return=True)``).

    Args:
        function: The callable to validate. When ``None``, return a decorator.
        config: Optional Pydantic ``ConfigDict`` overrides merged with the default config.
        validate_return: When ``True``, also validate the return value.

    Returns:
        The validated function, or a decorator that produces one.
    """
    config = {
        **_DEFAULT_VALIDATED_FUNCTION_CONFIG,
        **(config or {}),
    }

    from pydantic import validate_call

    return validate_call(config=config, validate_return=validate_return)(function)  # type: ignore


def get_args_model(
    function: Callable[..., Any],
    /,
    *,
    model_name: str | None = None,
    model_module: str | None = None,
    model_config: ConfigDict | None = None,
    model_base: type[BaseModel] | None = None,
    remove_self: bool = True,
    inner: bool = True,
) -> type[BaseModel]:
    """Generate a Pydantic ``BaseModel`` whose fields mirror a function's parameters.

    Inspect the function's signature and type hints to build a model class suitable for
    validating the function's arguments.

    Args:
        function: The callable whose signature to model.
        model_name: Name for the generated model class. Default to ``<FunctionName>Args``.
        model_module: Module name to assign to the generated model.
        model_config: Optional Pydantic ``ConfigDict`` for the model.
        model_base: Optional base class for the model.
        remove_self: When ``True``, exclude ``self`` from the model fields.
        inner: When ``True``, unwrap the function before inspecting it.

    Returns:
        A dynamically created ``BaseModel`` subclass with fields matching the function's
        parameters.
    """
    import inspect

    from pydantic import Field, create_model

    from ceres.__internal__.utilities.case import ucamelcase
    from ceres.__internal__.utilities.functions import get_inner_function

    function = get_inner_function(function) if inner else function

    if model_name is None:
        model_name = f"{ucamelcase(function.__name__)}Args"

    (
        position_parameter_names,
        _,
        kwargs_parameter_name,
        positional_parameter_defaults,
        keyword_only_parameter_names,
        keyword_only_parameter_defaults,
        _,
    ) = inspect.getfullargspec(function)

    annotations = get_type_hints(function, include_extras=True)
    position_parameter_names = position_parameter_names or []
    positional_parameter_defaults = positional_parameter_defaults or ()
    keyword_only_parameter_names = keyword_only_parameter_names or []
    keyword_only_parameter_defaults = keyword_only_parameter_defaults or {}

    if remove_self:
        position_parameter_names = [arg for arg in position_parameter_names if arg != "self"]

    positional_parameter_defaults = (Field(),) * (
        len(position_parameter_names) - len(positional_parameter_defaults)
    ) + positional_parameter_defaults

    positional_parameters = {
        name: (annotations.get(name, Any), default)
        for name, default in zip(position_parameter_names, positional_parameter_defaults)
    }
    keyword_only_parameters = {
        name: (annotations.get(name, Any), keyword_only_parameter_defaults.get(name, Field()))
        for name in keyword_only_parameter_names
    }

    parameters: dict[str, Any] = {**positional_parameters, **keyword_only_parameters}

    # Allow extra arguments if there is a `**kwargs` parameter in the function signature.
    if kwargs_parameter_name and model_base is None:
        model_config = (
            {**(model_config or {}), "extra": "allow"} if kwargs_parameter_name else model_config
        )

    model = create_model(
        model_name,
        __config__=model_config,
        __module__=model_module or "__dynamic__",
        __base__=model_base,
        **parameters,
    )

    model.__doc__ = function.__doc__

    return model
