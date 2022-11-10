import inspect
import sys
import typing
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from inspect import Parameter
from typing import (
    Any,
    Callable,
    ForwardRef,
    Generic,
    Mapping,
    Protocol,
    TypeVar,
    Union,
    cast,
)

from wrapt import ObjectProxy  # type: ignore

_T = TypeVar("_T")
_Key = Callable[..., _T]
_Factory = Callable[..., _T]


class _Context(Protocol):
    def get(self, key: Callable[..., _T]) -> _T:
        ...


class Container(_Context):
    def __init__(self) -> None:
        self._providers: dict[_Key[Any], Provider[Any]] = {}
        self._instances: dict[_Key[Any], Any] = {}

    def provide(self, key: _Key[_T], factory: _Factory[_T] | None = None) -> None:
        if factory is None:
            factory = key

        self.remove(key)
        self._providers[key] = FactoryProvider(factory)

    def set(self, key: _Key[_T], instance: _T) -> None:
        self._providers[key] = InstanceProvider(instance)
        self._instances[key] = instance

    def remove(self, key: _Key[_T]) -> _T | None:
        self._providers.pop(key, None)
        return cast(_T | None, self._instances.pop(key, None))

    def clear(self) -> None:
        self._providers.clear()
        self._instances.clear()

    def has_provider(self, key: _Key[_T]) -> bool:
        return key in self._providers

    def has_cached(self, key: _Key[_T]) -> bool:
        return key in self._instances

    def get(self, key: _Key[_T], *, cached: bool = True) -> _T:
        if cached and key in self._instances:
            return cast(_T, self._instances[key])

        if cached:
            # Create empty proxy object in cache.
            proxy = Proxy(None)
            self._instances[key] = proxy

        provider: Provider[_T] | None = self._providers.get(key)
        if not provider:
            provider = FactoryProvider(key)
            self._providers[key] = provider

        result = provider.provide(self)

        if cached:
            # Bind the proxy to the real instance.
            bind_proxy(proxy, result)  # type: ignore
            # Store the real instance in the cache.
            self._instances[key] = result

        return result


class ResolutionError(TypeError):
    def __init__(self, query: type):
        super().__init__(
            f"Container is not able to resolve type '{query}'. "
            f"Make sure it is registered in the container."
        )


class Provider(Generic[_T], metaclass=ABCMeta):
    @abstractmethod
    def provide(self, container: _Context) -> _T:
        ...


class InstanceProvider(Provider[_T]):
    def __init__(self, instance: _T):
        self._instance = instance

    def provide(self, container: _Context) -> _T:
        return self._instance

    def __hash__(self) -> int:
        return hash(("InstanceProvider", id(self._instance)))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, InstanceProvider) and self._instance == cast(
            _T,
            other._instance,  # type: ignore
        )


class FactoryProvider(Provider[_T]):
    def __init__(self, factory: Callable[..., _T]):
        self._factory = factory
        self._parameters = get_parameters(factory)
        self._scope = _type_forward_ref_scope(factory)

    def provide(self, container: _Context) -> _T:
        args: list[Any] = []
        kwargs: dict[str, Any] = {}

        for parameter in self._parameters:
            # Evaluate ForwardRefs for module-level declarations in the same module as the class.
            query = _evaluate_type(parameter.annotation, globals(), self._scope)

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


def get_parameters(factory: Callable[..., Any]) -> list[FactoryParameter]:
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


def _evaluate_type(
    type_: Any,
    globalns: Any,
    localns: Any,
    recursive_guard: frozenset[Any] = frozenset(),
) -> type:
    return _eval_type(type_, globalns, localns, recursive_guard)  # type: ignore


def _type_forward_ref_scope(type_: Union[type[_T], Callable[..., _T]]) -> Mapping[str, Any]:
    return getattr(sys.modules.get(type_.__module__, None), "__dict__", {})


class Proxy(ObjectProxy):  # type: ignore
    pass


def bind_proxy(proxy: Proxy, target: Any) -> None:
    proxy.__wrapped__ = target
