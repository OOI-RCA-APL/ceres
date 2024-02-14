import sys
from collections import defaultdict
from typing import Any


class LazyExport:
    def __init__(self, __name__: str) -> None:
        self.__module = sys.modules[__name__]
        self.__module.__getattr__ = self.get
        self.__exports: defaultdict[str, list[str]] = defaultdict(list)
        self.__export_mapping: dict[str, str] | None = None

    def __call__(self, path: str, *names: str) -> Any:
        self.__exports[path].extend(names)
        self.__export_mapping = None

    def get(self, name: str) -> object:
        path = self.__sync_mapping().get(name)
        if path is None:
            raise AttributeError(f"module {__name__} has no attribute {name}")

        from importlib import import_module

        module = import_module(path, package=__package__)
        return getattr(module, name)

    def __sync_mapping(self) -> dict[str, str]:
        if self.__export_mapping is None:
            self.__export_mapping = {}
            for path, names in self.__exports.items():
                for name in names:
                    self.__export_mapping[name] = path

        self.__module.__all__ = sorted(self.__export_mapping.keys())  # type: ignore
        return self.__export_mapping
