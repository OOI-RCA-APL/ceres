import importlib
import inspect
import traceback
from abc import ABC
from dataclasses import dataclass
from typing import Any, Callable, Generic, Optional, Type, TypeVar, cast

from .database import Database
from .exceptions import ObjectLoadException
from .internal import awaitify

ObjectT = TypeVar("ObjectT", bound="Object")


class Object(ABC):
    pass


async def load_object(descriptor: "ObjectDescriptor[ObjectT]", cls: Type[ObjectT]) -> ObjectT:
    if descriptor.instance:
        return descriptor.instance

    if not descriptor.module:
        raise ObjectLoadException("Descriptor has no module or instance.")

    try:
        module = importlib.import_module(descriptor.module)
    except ModuleNotFoundError:
        raise ObjectLoadException(f"Module '{descriptor.module}' was not found.")
    except Exception:
        raise ObjectLoadException(
            f"Module '{descriptor.module}' raised an exception while importing: {traceback.format_exc()}"
        )

    init: Callable[[], Any] = cast(Any, getattr(module, "init", None))

    if (
        not init
        or not inspect.isfunction(init)
        or len(inspect.signature(init).parameters.keys()) > 0
    ):
        raise ObjectLoadException(
            f"Module '{module}' must contain an 'init()' function that takes no arguments."
        )

    try:
        instance = await awaitify(init())
    except Exception:
        raise ObjectLoadException(
            f"Module '{module}' 'init()' raised an exception: {traceback.format_exc()}"
        )

    if not isinstance(instance, cls):
        raise ObjectLoadException(
            f"Module '{module}' 'init()' must return an instance of {cls}, got '{instance}'."
        )

    return instance


@dataclass(frozen=True, kw_only=True)
class ObjectDescriptor(Generic[ObjectT]):
    name: str
    module: Optional[str] = None
    instance: Optional[ObjectT] = None


@dataclass(frozen=True, kw_only=True)
class ObjectContext(Generic[ObjectT]):
    descriptor: ObjectDescriptor[ObjectT]
    database: Database
