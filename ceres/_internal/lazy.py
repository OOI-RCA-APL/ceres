import sys
from collections import defaultdict
from typing import Any


class LazyExport:
    def __init__(self, __name__: str) -> None:
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
