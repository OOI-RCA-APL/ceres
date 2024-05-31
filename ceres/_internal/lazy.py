from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from types import ModuleType, UnionType
from typing import TYPE_CHECKING, Any, Mapping, NoReturn, Sequence

from typing_extensions import override


class LazyExport:
    def __init__(self, __name__: str) -> None:
        import sys
        from collections import defaultdict

        self._module = sys.modules[__name__]
        self._module.__getattr__ = self.get
        self._exports: defaultdict[str, list[str]] = defaultdict(list)
        self._export_mapping: dict[str, str] | None = None

    def __call__(self, path: str, *names: str) -> Any:
        self._exports[path].extend(names)
        self._export_mapping = None

    def get(self, name: str) -> object:
        path = self.__sync_mapping().get(name)
        if path is None:
            raise AttributeError(f"module {__name__} has no attribute {name}")

        from importlib import import_module

        try:
            module = import_module(path, package=__package__)
        except Exception as exception:
            raise ImportError(
                f"cannot import name {name} from {path} due to exception {exception}"
            ) from exception

        return getattr(module, name)

    def __sync_mapping(self) -> dict[str, str]:
        if self._export_mapping is None:
            self._export_mapping = {}
            for path, names in self._exports.items():
                for name in names:
                    self._export_mapping[name] = path

        self._module.__all__ = sorted(self._export_mapping.keys())  # type: ignore
        return self._export_mapping


class ProxiedMethods:
    if TYPE_CHECKING:

        def __proxy_get__(self) -> Any: ...

    @override
    def __dir__(self) -> list[str]:
        return dir(self.__proxy_get__())

    @override
    def __str__(self) -> str:
        return str(self.__proxy_get__())

    @override
    def __repr__(self) -> str:
        return repr(self.__proxy_get__())

    def __bytes__(self) -> bytes:
        return bytes(self.__proxy_get__())

    def __reversed__(self) -> Any:
        return reversed(self.__proxy_get__())

    def __round__(self) -> Any:
        return round(self.__proxy_get__())

    def __ceil__(self) -> Any:
        return self.__proxy_get__().__ceil__()

    def __floor__(self) -> Any:
        return self.__proxy_get__().__floor__()

    @override
    def __format__(self, __format_spec: Any) -> Any:
        return format(self.__proxy_get__(), __format_spec)

    def __trunc__(self) -> Any:
        return self.__proxy_get__().__trunc__()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.__proxy_get__()(*args, **kwargs)

    def __mro_entries__(self, bases: Any) -> Any:
        return (self.__proxy_get__(),)

    def __lt__(self, other: Any) -> Any:
        return self.__proxy_get__() < other

    def __le__(self, other: Any) -> Any:
        return self.__proxy_get__() <= other

    @override
    def __eq__(self, other: Any) -> Any:
        return self.__proxy_get__() == other

    @override
    def __ne__(self, other: Any) -> Any:
        return self.__proxy_get__() != other

    def __gt__(self, other: Any) -> Any:
        return self.__proxy_get__() > other

    def __ge__(self, other: Any):
        return self.__proxy_get__() >= other

    @override
    def __hash__(self) -> Any:
        return hash(self.__proxy_get__())

    def __nonzero__(self) -> Any:
        return bool(self.__proxy_get__())

    def __bool__(self) -> Any:
        return bool(self.__proxy_get__())

    def __add__(self, other: Any) -> Any:
        return self.__proxy_get__() + other

    def __sub__(self, other: Any) -> Any:
        return self.__proxy_get__() - other

    def __mul__(self, other: Any) -> Any:
        return self.__proxy_get__() * other

    def __truediv__(self, other: Any) -> Any:
        return self.__proxy_get__() / other

    def __floordiv__(self, other: Any) -> Any:
        return self.__proxy_get__() // other

    def __mod__(self, other: Any) -> Any:
        return self.__proxy_get__() % other

    def __divmod__(self, other: Any) -> Any:
        return divmod(self.__proxy_get__(), other)

    def __pow__(self, other: Any, *args: Any) -> Any:
        return pow(self.__proxy_get__(), other, *args)

    def __lshift__(self, other: Any) -> Any:
        return self.__proxy_get__() << other

    def __rshift__(self, other: Any) -> Any:
        return self.__proxy_get__() >> other

    def __and__(self, other: Any) -> Any:
        return self.__proxy_get__() & other

    def __xor__(self, other: Any) -> Any:
        return self.__proxy_get__() ^ other

    def __or__(self, other: Any) -> Any:
        return self.__proxy_get__() | other

    def __radd__(self, other: Any) -> Any:
        return other + self.__proxy_get__()

    def __rsub__(self, other: Any) -> Any:
        return other - self.__proxy_get__()

    def __rmul__(self, other: Any) -> Any:
        return other * self.__proxy_get__()

    def __rtruediv__(self, other: Any) -> Any:
        return other / self.__proxy_get__()

    def __rfloordiv__(self, other: Any) -> Any:
        return other // self.__proxy_get__()

    def __rmod__(self, other: Any) -> Any:
        return other % self.__proxy_get__()

    def __rdivmod__(self, other: Any) -> Any:
        return divmod(other, self.__proxy_get__())

    def __rpow__(self, other: Any, *args: Any) -> Any:
        return pow(other, self.__proxy_get__(), *args)

    def __rlshift__(self, other: Any) -> Any:
        return other << self.__proxy_get__()

    def __rrshift__(self, other: Any) -> Any:
        return other >> self.__proxy_get__()

    def __rand__(self, other: Any) -> Any:
        return other & self.__proxy_get__()

    def __rxor__(self, other: Any) -> Any:
        return other ^ self.__proxy_get__()

    def __ror__(self, other: Any) -> Any:
        return other | self.__proxy_get__()

    def __iadd__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped += other
        return self

    def __isub__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped -= other
        return self

    def __imul__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped *= other
        return self

    def __itruediv__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped = wrapped / other
        return self

    def __ifloordiv__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped //= other
        return self

    def __imod__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped %= other
        return self

    def __ipow__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped **= other
        return self

    def __ilshift__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped <<= other
        return self

    def __irshift__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped >>= other
        return self

    def __iand__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped &= other
        return self

    def __ixor__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped ^= other
        return self

    def __ior__(self, other: Any) -> Any:
        wrapped = self.__proxy_get__()
        wrapped |= other
        return self

    def __neg__(self) -> Any:
        return -self.__proxy_get__()

    def __pos__(self) -> Any:
        return +self.__proxy_get__()

    def __abs__(self) -> Any:
        return abs(self.__proxy_get__())

    def __invert__(self) -> Any:
        return ~self.__proxy_get__()

    def __int__(self) -> Any:
        return int(self.__proxy_get__())

    def __float__(self) -> Any:
        return float(self.__proxy_get__())

    def __complex__(self) -> Any:
        return complex(self.__proxy_get__())

    def __oct__(self) -> Any:
        return oct(self.__proxy_get__())

    def __hex__(self) -> Any:
        return hex(self.__proxy_get__())

    def __index__(self) -> Any:
        import operator

        return operator.index(self.__proxy_get__())

    def __len__(self) -> Any:
        return len(self.__proxy_get__())

    def __contains__(self, value: Any) -> Any:
        return value in self.__proxy_get__()

    def __getitem__(self, key: Any) -> Any:
        return self.__proxy_get__()[key]

    def __setitem__(self, key: Any, value: Any) -> None:
        self.__proxy_get__()[key] = value

    def __delitem__(self, key: Any) -> None:
        del self.__proxy_get__()[key]

    def __getslice__(self, i: Any, j: Any) -> Any:
        return self.__proxy_get__()[i:j]

    def __setslice__(self, i: Any, j: Any, value: Any) -> None:
        self.__proxy_get__()[i:j] = value

    def __delslice__(self, i: Any, j: Any) -> None:
        del self.__proxy_get__()[i:j]

    def __enter__(self) -> Any:
        return self.__proxy_get__().__enter__()

    def __exit__(self, *args: Any, **kwargs: Any) -> Any:
        return self.__proxy_get__().__exit__(*args, **kwargs)

    def __iter__(self) -> Any:
        return iter(self.__proxy_get__())

    def __copy__(self) -> NoReturn:
        raise NotImplementedError()

    def __deepcopy__(self, memo: Any) -> NoReturn:
        raise NotImplementedError()

    @override
    def __reduce__(self) -> NoReturn:
        raise NotImplementedError()

    @override
    def __reduce_ex__(self, protocol: Any) -> NoReturn:
        raise NotImplementedError()


_proxy_dynamic_cls_cache: dict[type, type["LazyProxy"]] = {}

_undefined = object()


class LazyProxy:
    # __slots__ = (
    #     "__proxy_module__",
    #     "__proxy_proxied_attrs__",
    #     "__proxy_target_attr__",
    #     "__proxy_target__",
    # )

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
        return isinstance(instance, self.__proxy_get__())

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.__proxy_get__()(*args, **kwargs)

    def __or__(self, value: Any) -> UnionType:
        return self.__proxy_get__() | value

    def __ror__(self, value: Any) -> UnionType:
        return value | self.__proxy_get__()

    def __getitem__(self, key: Any) -> Any:
        return self.__proxy_get__()[key]

    def __proxy_sync_dynamic_class__(self) -> type["LazyProxy"]:
        current = self.__proxy_get_dynamic_class__()
        if self.__class__ is not current:
            self.__class__ = current

        return current

    def __proxy_get_dynamic_class__(self) -> type["LazyProxy"]:
        target = self.__proxy_get__()
        key = type(target)

        cached = _proxy_dynamic_cls_cache.get(key)
        if cached is not None:
            return cached

        target_names = set(dir(type(target)))
        proxy_names = LazyProxy.__dict__.keys()
        class_attrs: dict[str, Any] = {}

        for name in target_names:
            if name not in proxy_names:
                proxy = ProxiedMethods.__dict__.get(name)
                if proxy is not None:
                    class_attrs[name] = proxy

        Specialized = type("Specialized", (LazyProxy,), class_attrs)
        Specialized.__name__ = LazyProxy.__name__ + f"[{type(target).__name__}]"
        Specialized.__qualname__ = LazyProxy.__qualname__.replace(
            LazyProxy.__name__,
            Specialized.__name__,
        )

        _proxy_dynamic_cls_cache[key] = Specialized
        return Specialized

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
        self.__proxy_sync_dynamic_class__()
        return target


_lazy_proxy_cache_lock = Lock()
_lazy_proxy_cache: dict[tuple[str, tuple[str, ...], str | None], LazyProxy] = {}


def _get_cached_lazy_proxy(
    module: str,
    proxied_attrs: tuple[str, ...] = (),
    target_attr: str | None = None,
) -> LazyProxy:
    key = (module, proxied_attrs, target_attr)
    with _lazy_proxy_cache_lock:
        proxy = _lazy_proxy_cache.get(key)
        if proxy is None:
            proxy = LazyProxy(module, proxied_attrs, target_attr)
            _lazy_proxy_cache[key] = proxy

    return proxy


_import_original = __import__
_current_lazy_importing_modules: set[str] = set()


def __lazy_import__(
    name: str,
    globals: Mapping[str, object] | None | None = None,
    locals: Mapping[str, object] | None = None,
    fromlist: Sequence[str] | None = None,
    level: int = 0,
) -> ModuleType | LazyProxy:
    if locals is not None:
        caller = locals.get("__name__")
        if caller is not None and caller in _current_lazy_importing_modules:
            return _get_cached_lazy_proxy(name, tuple(fromlist or ()))

    return _import_original(
        name,
        globals,
        locals,
        fromlist,  # type: ignore
        level,
    )


@contextmanager
def lazy_imports(name: str):
    if __builtins__.get("__import__") is not __lazy_import__:
        __builtins__["__import__"] = __lazy_import__

    _current_lazy_importing_modules.add(name)
    try:
        yield
    finally:
        _current_lazy_importing_modules.remove(name)
