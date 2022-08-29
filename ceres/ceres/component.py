from __future__ import annotations

import importlib
import inspect
import traceback
from abc import ABC
from typing import Any, TypeVar

from pydantic import ValidationError, validate_arguments

from .exceptions import ComponentLoadException
from .internal import format_validation_error

ComponentT = TypeVar("ComponentT", bound="Component")


class Component(ABC):
    @classmethod
    def load(
        cls: type[ComponentT],
        source: str | object,
        parameters: dict[str, Any] = {},
    ) -> ComponentT:
        if not isinstance(source, str):
            if not isinstance(source, cls):
                raise ComponentLoadException(
                    f"Component passed in configuration must be an instance of {cls}, got {source}."
                )

            return source

        try:
            module = importlib.import_module(source)
        except ModuleNotFoundError:
            raise ComponentLoadException(f"Module '{source}' was not found.")
        except Exception:
            raise ComponentLoadException(
                f"Component module {source} raised an exception while importing: {traceback.format_exc()}"
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
            raise ComponentLoadException(
                f"Component module {module} must contain class a non-abstract subclass of {cls}."
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
            raise ComponentLoadException(
                f"Invalid parameters for {target_cls}: {format_validation_error(error)}"
            )

        try:
            __init__(instance, **arguments)
        except Exception:
            raise ComponentLoadException(
                f"Exception raised during initialization for {target_cls}: {traceback.format_exc()}"
            )

        return instance
