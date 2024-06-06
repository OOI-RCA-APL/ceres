from __future__ import annotations

from typing import override

from fastapi.staticfiles import StaticFiles

from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    import os
    from pathlib import Path


class ConsoleFiles(StaticFiles):
    def __init__(self) -> None:

        directory = Path(__file__).parent / "../../static/console"
        directory = directory.resolve()
        directory.mkdir(mode=755, parents=True, exist_ok=True)
        super().__init__(directory=directory, html=True)

    @override
    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        path, result = super().lookup_path(path)
        if result is None:
            path, result = super().lookup_path("index.html")

        return (path, result)
