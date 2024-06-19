from __future__ import annotations

import sys
from contextlib import contextmanager
from threading import Lock
from types import ModuleType, UnionType
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence, overload, override, Final

_undefined = object()


class LazyProxy:
    __slots__ = (
        "__proxy_module__",
        "__proxy_proxied_attrs__",
        "__proxy_target_attr__",
        "__proxy_target__",
    )

    def __init__(
        self,
        module: str,
        proxied_attrs: tuple[str, ...] = (),
        target_attr: str | None = None,
    ) -> None:
        if TYPE_CHECKING:
            self.__proxy_module__ = module
            self.__proxy_proxied_attrs__ = proxied_attrs
            self.__proxy_target_attr__ = target_attr
            self.__proxy_target__ = _undefined
        else:
            object.__setattr__(self, "__proxy_module__", module)
            object.__setattr__(self, "__proxy_proxied_attrs__", proxied_attrs)
            object.__setattr__(self, "__proxy_target_attr__", target_attr)
            object.__setattr__(self, "__proxy_target__", _undefined)

    @override
    def __getattribute__(self, name: str) -> Any:
        if name == "__class__":
            return self.__proxy_get__().__class__

        return super().__getattribute__(name)

    def __getattr__(self, name: str) -> Any:
        if name in self.__proxy_proxied_attrs__:
            return _get_cached_lazy_proxy(self.__proxy_module__, (), name)

        return getattr(self.__proxy_get__(), name)

    @override
    def __setattr__(self, name: str, value: Any) -> None:
        if hasattr(type(self), name) or hasattr(self, name):
            object.__setattr__(self, name, value)
        else:
            setattr(self.__proxy_get__(), name, value)

    def __instancecheck__(self, instance: Any) -> bool:
        return isinstance(instance, self.__proxy_get__()) or type(self) in type(instance).__mro__

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.__proxy_get__()(*args, **kwargs)

    def __or__(self, value: Any) -> UnionType:
        return self.__proxy_get__() | value

    def __ror__(self, value: Any) -> UnionType:
        return value | self.__proxy_get__()

    def __getitem__(self, key: Any) -> Any:
        return self.__proxy_get__()[key]

    def __proxy_get__(self) -> Any:
        if self.__proxy_target__ is not _undefined:
            return self.__proxy_target__

        import importlib

        module = importlib.import_module(self.__proxy_module__)
        if self.__proxy_target_attr__ is None:
            target = module
        else:
            target = getattr(module, self.__proxy_target_attr__)

        self.__proxy_target__ = target
        return target


_lazy_proxy_cache: dict[tuple[str, tuple[str, ...], str | None], LazyProxy] = {}


def _get_cached_lazy_proxy(
    module: str,
    proxied_attrs: tuple[str, ...] = (),
    target_attr: str | None = None,
) -> LazyProxy:
    key = (module, proxied_attrs, target_attr)
    proxy = _lazy_proxy_cache.get(key)
    if proxy is None:
        proxy = LazyProxy(module, proxied_attrs, target_attr)
        _lazy_proxy_cache.setdefault(key, proxy)

    return proxy


_original__import__: Final = __import__
_lazy_importing_modules: Final[set[str]] = set()
_lazy_importing_modules_lock: Final = Lock()
_LAZY_EXPORTS_NAME: Final = "__lazy_exports__"


def __lazy_import__(
    name: str,
    globals: Mapping[str, object] | None = None,
    locals: Mapping[str, object] | None = None,
    fromlist: Sequence[str] | None = None,
    level: int = 0,
) -> ModuleType | LazyProxy:
    if locals is not None:
        module__name__ = locals.get("__name__")
        if module__name__ is not None and module__name__ in _lazy_importing_modules:
            return _get_cached_lazy_proxy(name, tuple(fromlist or ()))

    return _original__import__(
        name,
        globals,
        locals,
        fromlist,  # type: ignore
        level,
    )


@contextmanager
def lazy_imports(module__name__: str, /, *, export: bool = False):
    with _lazy_importing_modules_lock:
        _lazy_importing_modules.add(module__name__)
        if __builtins__.get("__import__") is not __lazy_import__:
            __builtins__["__import__"] = __lazy_import__

    module = sys.modules[module__name__]
    original_names: frozenset[str] = frozenset(module.__dict__) if export else frozenset()

    try:
        yield
    finally:
        with _lazy_importing_modules_lock:
            module__dict__ = module.__dict__
            _lazy_importing_modules.discard(module__name__)
            if not _lazy_importing_modules:
                __builtins__["__import__"] = _original__import__

        if export:
            added_names = set(module__dict__) - original_names
            module__lazy_exports__: dict[str, LazyProxy] = module.__dict__.setdefault(
                _LAZY_EXPORTS_NAME, {}
            )

            __all__: list[str] = module__dict__.setdefault("__all__", [])
            if not isinstance(__all__, list):
                __all__ = list(__all__) if isinstance(__all__, Iterable) else []
                module__dict__["__all__"] = __all__

            for name in added_names:
                value = module__dict__[name]
                if isinstance(value, LazyProxy):
                    module__lazy_exports__[name] = value
                    del module__dict__[name]
                    __all__.append(name)

            def __lazy_getattr__(name: str) -> object:
                module = sys.modules[module__name__]
                module__dict__ = module.__dict__
                module__lazy_exports__: dict[str, LazyProxy] | None = module__dict__.get(
                    _LAZY_EXPORTS_NAME
                )
                if module__lazy_exports__ is not None:
                    proxy = module__lazy_exports__.get(name)
                    if proxy is not None:
                        return module__dict__.setdefault(name, proxy.__proxy_get__())

                raise AttributeError(f"module {module__name__} has no attribute {name}")

            module__dict__["__getattr__"] = __lazy_getattr__


@overload
def unlazy(value: LazyProxy) -> Any: ...


@overload
def unlazy[T](value: T) -> T: ...


def unlazy[T](value: T | LazyProxy) -> T:
    if isinstance(value, LazyProxy):
        return value.__proxy_get__()

    return value
