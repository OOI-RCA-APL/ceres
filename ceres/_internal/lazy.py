from __future__ import annotations

import sys
from contextlib import contextmanager
from threading import Lock
from types import ModuleType, UnionType
from typing import TYPE_CHECKING, Any, Mapping, Sequence, overload, override

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


_original__import__ = __import__
_lazy_importing_modules: set[str] = set()


def __lazy_import__(
    name: str,
    globals: Mapping[str, object] | None | None = None,
    locals: Mapping[str, object] | None = None,
    fromlist: Sequence[str] | None = None,
    level: int = 0,
) -> ModuleType | LazyProxy:
    if locals is not None:
        caller = locals.get("__name__")
        if caller is not None and caller in _lazy_importing_modules:
            return _get_cached_lazy_proxy(name, tuple(fromlist or ()))

    return _original__import__(
        name,
        globals,
        locals,
        fromlist,  # type: ignore
        level,
    )


def _setup_lazy_exports(__name__: str):
    lazy_attr_prefix = "__lazy__"
    lazy_lock_name = "__lazy_setup_lock__"

    module = sys.modules[__name__]

    attrs = module.__dict__
    if lazy_lock_name not in attrs:
        attrs.setdefault(lazy_lock_name, Lock())

    with attrs[lazy_lock_name]:
        for key, value in list(attrs.items()):
            if key.startswith(lazy_attr_prefix):
                continue

            if isinstance(value, LazyProxy):
                del attrs[key]
                attrs[lazy_attr_prefix + key] = value

        def __lazy_getattr__(name: str) -> object:
            lazy_key = lazy_attr_prefix + name
            if lazy_key in attrs:
                value = unwrap(attrs[lazy_key])
                attrs[name] = value
                attrs.pop(lazy_key, None)
                return value

            raise AttributeError(f"module {name} has no attribute {name}")

        module.__getattr__ = __lazy_getattr__


@contextmanager
def lazy_imports(__name__: str, export: bool = False):
    if __builtins__.get("__import__") is not __lazy_import__:
        __builtins__["__import__"] = __lazy_import__

    _lazy_importing_modules.add(__name__)
    try:
        yield
    finally:
        _lazy_importing_modules.discard(__name__)

    if export:
        _setup_lazy_exports(__name__)


@overload
def unwrap(value: LazyProxy) -> Any: ...


@overload
def unwrap[T](value: T) -> T: ...


def unwrap[T](value: T | LazyProxy) -> T:
    if isinstance(value, LazyProxy):
        return value.__proxy_get__()

    return value
