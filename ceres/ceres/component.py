from __future__ import annotations

import importlib
import inspect
import traceback
from abc import ABC
from enum import Enum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError, validate_arguments

from .result import Fail, Ok, Result
from .validation import ValidationProblem

ComponentT = TypeVar("ComponentT", bound="Component")


class ComponentLoadErrorKind(str, Enum):
    INVALID_COMPONENT_CLASS = "invalid-component-class"
    COMPONENT_MODULE_NOT_FOUND = "component-module-not-found"
    COMPONENT_MODULE_EXCEPTION = "component-module-exception"
    COMPONENT_CLASS_NOT_FOUND = "component-class-not-found"
    COMPONENT_INIT_EXCEPTION = "component-init-exception"
    INVALID_COMPONENT_PARAMETERS = "invalid-component-parameters"


class BaseComponentLoadError(BaseModel):
    kind: ComponentLoadErrorKind
    message: str


class InvalidComponentClassError(BaseComponentLoadError):
    kind: Literal[
        ComponentLoadErrorKind.INVALID_COMPONENT_CLASS
    ] = ComponentLoadErrorKind.INVALID_COMPONENT_CLASS


class ComponentModuleNotFoundError(BaseComponentLoadError):
    kind: Literal[
        ComponentLoadErrorKind.COMPONENT_MODULE_NOT_FOUND
    ] = ComponentLoadErrorKind.COMPONENT_MODULE_NOT_FOUND


class ComponentModuleExceptionError(BaseComponentLoadError):
    kind: Literal[
        ComponentLoadErrorKind.COMPONENT_MODULE_EXCEPTION
    ] = ComponentLoadErrorKind.COMPONENT_MODULE_EXCEPTION
    traceback: str


class ComponentClassNotFoundError(BaseComponentLoadError):
    kind: Literal[
        ComponentLoadErrorKind.COMPONENT_CLASS_NOT_FOUND
    ] = ComponentLoadErrorKind.COMPONENT_CLASS_NOT_FOUND


class InvalidComponentParametersError(BaseComponentLoadError):
    kind: Literal[
        ComponentLoadErrorKind.INVALID_COMPONENT_PARAMETERS
    ] = ComponentLoadErrorKind.INVALID_COMPONENT_PARAMETERS
    problems: list[ValidationProblem]


class ComponentInitExceptionError(BaseComponentLoadError):
    kind: Literal[
        ComponentLoadErrorKind.COMPONENT_INIT_EXCEPTION
    ] = ComponentLoadErrorKind.COMPONENT_INIT_EXCEPTION
    traceback: str


ComponentLoadError = (
    InvalidComponentClassError
    | ComponentModuleNotFoundError
    | ComponentModuleExceptionError
    | ComponentClassNotFoundError
    | InvalidComponentParametersError
    | ComponentInitExceptionError
)


class Component(ABC):
    @classmethod
    def load(
        cls: type[ComponentT],
        source: str | object,
        parameters: dict[str, Any] = {},
    ) -> Result[ComponentT, ComponentLoadError]:
        if not isinstance(source, str):
            if not isinstance(source, cls):
                return Fail(
                    InvalidComponentClassError(
                        message=f"Component passed in configuration must be an instance of {cls}, got {source}."
                    )
                )

            return Ok(source)

        try:
            module = importlib.import_module(source)
        except Exception as exception:
            if isinstance(exception, ModuleNotFoundError) and exception.name == source:
                return Fail(
                    ComponentModuleNotFoundError(
                        message=f"Component module '{source}' was not found."
                    )
                )

            return Fail(
                ComponentModuleExceptionError(
                    message=f"Component module '{source}' raised an exception during import.",
                    traceback=traceback.format_exc(),
                )
            )

        target_cls: type[ComponentT] | None = None

        for _, member in inspect.getmembers(module):
            if (
                inspect.isclass(member)
                and issubclass(member, cls)
                and not inspect.isabstract(member)
            ):
                target_cls = member
                break

        if target_cls is None:
            return Fail(
                InvalidComponentClassError(
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
                InvalidComponentParametersError(
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
