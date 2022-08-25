import importlib
import inspect
import traceback
from abc import ABC
from typing import Any, Callable, Type, TypeVar, Union, cast

from .exceptions import ComponentLoadException
from .internal import awaitify

ComponentT = TypeVar("ComponentT", bound="Component")


class Component(ABC):
    @classmethod
    async def load(cls: Type[ComponentT], source: Union[str, object]) -> ComponentT:
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
                f"Module '{source}' raised an exception while importing: {traceback.format_exc()}"
            )

        init: Callable[[], Any] = cast(Any, getattr(module, "init", None))

        if (
            not init
            or not inspect.isfunction(init)
            or len(inspect.signature(init).parameters.keys()) > 0
        ):
            raise ComponentLoadException(
                f"Module '{module}' must contain an 'init()' function that takes no arguments."
            )

        try:
            instance = await awaitify(init())
        except Exception:
            raise ComponentLoadException(
                f"Module '{module}' 'init()' raised an exception: {traceback.format_exc()}"
            )

        if not isinstance(instance, cls):
            raise ComponentLoadException(
                f"Module '{module}' 'init()' must return an instance of {cls}, got {instance}."
            )

        return instance
