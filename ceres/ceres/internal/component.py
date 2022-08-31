from __future__ import annotations

import importlib
import inspect
import traceback
from typing import Any, TypeVar

from pydantic import ValidationError, validate_arguments

from ..component import Component
from ..errors import (
    ComponentClassInvalidError,
    ComponentError,
    ComponentInitExceptionError,
    ComponentModuleExceptionError,
    ComponentModuleNotFoundError,
    ComponentParametersInvalidError,
    ValidationProblem,
)
from ..result import Fail, Ok, Result

ComponentT = TypeVar("ComponentT", bound="Component[Any]")


def load_component(
    cls: type[ComponentT],
    source: str | object,
    parameters: dict[str, Any],
) -> Result[ComponentT, ComponentError]:
    if not isinstance(source, str):
        if not isinstance(source, cls):
            return Fail(
                ComponentClassInvalidError(
                    message=f"Component passed in configuration must be an instance of {cls}, got {source}."
                )
            )

        return Ok(source)

    try:
        module = importlib.import_module(source)
    except Exception as exception:
        if isinstance(exception, ModuleNotFoundError) and exception.name == source:
            return Fail(
                ComponentModuleNotFoundError(message=f"Component module '{source}' was not found.")
            )

        return Fail(
            ComponentModuleExceptionError(
                message=f"Component module '{source}' raised an exception during import.",
                traceback=traceback.format_exc(),
            )
        )

    target_cls: type[ComponentT] | None = None

    # Find the last non-abstract class in the module that is a subclass of the "cls" argument.
    for _, member in inspect.getmembers(module):
        if inspect.isclass(member) and issubclass(member, cls) and not inspect.isabstract(member):
            target_cls = member

    if target_cls is None:
        return Fail(
            ComponentClassInvalidError(
                message=f"Component module {module} must contain class a non-abstract subclass of {cls}."
            )
        )

    signature = inspect.signature(target_cls)
    arguments: dict[str, Any] = {}

    # If there is a component argument named "parameters", assign all parameters to it as a
    # dictionary. This allows using constructor arguments or a dedicated "parameters" type.
    if "parameters" in signature.parameters:
        for name, value in parameters.items():
            if name in signature.parameters:
                arguments[name] = value

        arguments["parameters"] = {**parameters}
    else:
        arguments = {**parameters}

    __init__ = validate_arguments(target_cls.__init__)
    instance = target_cls.__new__(target_cls)

    try:
        __init__.validate(instance, **arguments)  # type: ignore
    except ValidationError as error:
        return Fail(
            ComponentParametersInvalidError(
                message=f"Invalid parameters for {target_cls}.",
                problems=ValidationProblem.extract(error),
            )
        )

    try:
        __init__(instance, **arguments)
    except Exception:
        return Fail(
            ComponentInitExceptionError(
                message=f"Exception raised when calling __init__() for {target_cls}.",
                traceback=traceback.format_exc(),
            )
        )

    return Ok(instance)
