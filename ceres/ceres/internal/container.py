from __future__ import annotations

import inspect
import sys
import typing
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from functools import partial, partialmethod
from inspect import Parameter
from typing import (
    Any,
    Callable,
    ForwardRef,
    Generic,
    Mapping,
    Protocol,
    TypeGuard,
    TypeVar,
    Union,
    cast,
    get_type_hints,
)

from zope.proxy import ProxyBase, isProxy, setProxiedObject

T = TypeVar("T")

__all__ = ["Container", "ResolutionError"]


Key = Callable[..., T]
Factory = Callable[..., T]


class ContainerContext(Protocol):
    def get(self, key: Callable[..., T]) -> T:
        ...


class Container(ContainerContext):
    def __init__(self) -> None:
        self._providers: dict[Key, Provider] = {}
        self._instances: dict[Key, Any] = {}

    def provide(self, key: Key[T], factory: Factory[T] | None = None) -> None:
        if factory is None:
            factory = key

        self.remove(key)
        self._providers[key] = FactoryProvider(factory)

    def set(self, key: Key[T], instance: T) -> None:
        self._providers[key] = InstanceProvider(instance)
        self._instances[key] = instance

    def remove(self, key: Key[T]) -> T | None:
        self._providers.pop(key, None)
        return cast(T | None, self._instances.pop(key, None))

    def clear(self) -> None:
        self._providers.clear()
        self._instances.clear()

    def has_provider(self, key: Key[T]) -> bool:
        return key in self._providers

    def has_cached(self, key: Key[T]) -> bool:
        return key in self._instances

    def get(self, key: Key[T], *, cached: bool = True) -> T:
        if cached and key in self._instances:
            return cast(T, self._instances[key])

        if cached:
            # Create empty proxy object in cache.
            proxy = Proxy(None)
            self._instances[key] = proxy

        provider: Provider[T] | None = self._providers.get(key)
        if not provider:
            provider = FactoryProvider(key)
            self._providers[key] = provider

        result = provider.provide(self)

        if cached:
            # Bind the proxy to the real instance.
            bind_proxy(proxy, result)
            # Store the real instance in the cache.
            self._instances[key] = result

        return result

    # def _register(self, key: Key[T], provider: Provider[T]) -> None:
    #     self._providers[key] = provider


class ResolutionError(TypeError):
    def __init__(self, query: type):
        super().__init__(
            f"Container is not able to resolve type '{query}'. "
            f"Make sure it is registered in the container."
        )


class Provider(Generic[T], metaclass=ABCMeta):
    @abstractmethod
    def provide(self, container: ContainerContext) -> T:
        ...


class InstanceProvider(Provider[T]):
    def __init__(self, instance: T):
        self._instance = instance

    def provide(self, container: ContainerContext) -> T:
        return self._instance

    def __hash__(self) -> int:
        return hash(("InstanceProvider", id(self._instance)))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, InstanceProvider) and self._instance == other._instance


class FactoryProvider(Provider[T]):
    def __init__(self, factory: Callable[..., T]):
        self._factory = factory
        self._parameters = get_parameters(factory)
        self._scope = type_forward_ref_scope(factory)

    def provide(self, container: ContainerContext) -> T:
        args: list[Any] = []
        kwargs: dict[str, Any] = {}

        for parameter in self._parameters:
            # Evaluate ForwardRefs for module-level declarations in the same module as the class.
            query = evaluate_type(parameter.annotation, globals(), self._scope)

            try:
                if parameter.positional:
                    args.append(container.get(query))
                else:
                    kwargs[parameter.name] = container.get(query)
            except ResolutionError:
                if not parameter.defaulted:
                    raise

        return self._factory(*args, **kwargs)

    def __hash__(self) -> int:
        return hash(("FactoryProvider", self._factory))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FactoryProvider) and self._factory == other._factory


@dataclass(kw_only=True, frozen=True)
class FactoryParameter:
    name: str
    annotation: type | ForwardRef | Any
    positional: bool
    default: Any
    defaulted: bool


def get_parameters(factory: Callable[..., T]) -> list[FactoryParameter]:
    parameters: list[FactoryParameter] = []

    try:
        signature = inspect.signature(factory)
    except Exception:
        return parameters

    for name, parameter in signature.parameters.items():
        annotation = parameter.annotation
        positional = parameter.kind == Parameter.VAR_POSITIONAL
        default = parameter.default
        defaulted = parameter.default is not Parameter.empty

        # **kwargs are not supported.
        if parameter.kind == Parameter.VAR_KEYWORD:
            continue

        # Check for missing type annotation.
        if annotation is Parameter.empty:
            if not defaulted:
                raise TypeError(
                    f"Missing annotation (or default) for parameter '{name}' of {factory}. "
                    f"Container won't be able to resolve this type."
                )
        else:
            # If the annotation is just a string assume it's a ForwardRef.
            if isinstance(annotation, str):
                annotation = ForwardRef(annotation)

            parameters.append(
                FactoryParameter(
                    name=name,
                    annotation=annotation,
                    positional=positional,
                    default=default,
                    defaulted=defaulted,
                )
            )

    return parameters


_eval_type = getattr(typing, "_eval_type")


def evaluate_type(
    type_: Any,
    globalns: Any,
    localns: Any,
    recursive_guard: frozenset[Any] = frozenset(),
) -> type:
    return _eval_type(type_, globalns, localns, recursive_guard)  # type: ignore


def unwrap_decorators(obj: Any) -> Any:
    while hasattr(obj, "__wrapped__"):
        obj = obj.__wrapped__
    return obj


def get_return_type(obj: type[T] | Callable[..., T]) -> type[T]:
    obj = unwrap_decorators(obj)

    if isinstance(obj, type):
        return obj

    if isinstance(obj, (partial, partialmethod)):
        return get_return_type(obj.func)

    try:
        type_hints = get_type_hints(obj)
    except TypeError:
        type_hints = get_type_hints(obj.__call__)  # type: ignore

    if "return" not in type_hints:
        raise TypeError(f"Missing return type annotation for {obj}")

    return cast(type[T], type_hints["return"])


def type_forward_ref_scope(type_: Union[type[T], Callable[..., T]]) -> Mapping[str, Any]:
    return getattr(sys.modules.get(type_.__module__, None), "__dict__", {})


class Proxy(ProxyBase):  # type: ignore
    pass


def bind_proxy(proxy: Proxy, target: Any) -> None:
    setProxiedObject(proxy, target)


def is_proxy(value: Any) -> TypeGuard[Proxy]:
    return bool(isProxy(value, Proxy))


def get_origin(type_: Any) -> Any:
    if type_ is Generic:
        return type_
    return getattr(type_, "__origin__", None)
