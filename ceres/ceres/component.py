import importlib
import inspect
import traceback
from abc import ABC
from typing import Any, Callable, Type, TypeVar, cast

from .config import ComponentConfig
from .exceptions import ComponentLoadException
from .internal import awaitify


class Component(ABC):
    pass


ComponentT = TypeVar("ComponentT", bound="Component")


async def load_component(config: "ComponentConfig", cls: Type[ComponentT]) -> ComponentT:
    if not isinstance(config.component, str):
        if not isinstance(config.component, cls):
            raise ComponentLoadException(
                f"Component passed in configuration must be an instance of {cls}, got {config.component}."
            )

        return config.component

    try:
        module = importlib.import_module(config.component)
    except ModuleNotFoundError:
        raise ComponentLoadException(f"Module '{config.component}' was not found.")
    except Exception:
        raise ComponentLoadException(
            f"Module '{config.component}' raised an exception while importing: {traceback.format_exc()}"
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
