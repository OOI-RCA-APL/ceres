import os
from pathlib import Path

from fastapi.staticfiles import StaticFiles


class Static(StaticFiles):
    def __init__(self) -> None:
        super().__init__(
            directory=Path(__file__).parent / "static",
            html=True,
            check_dir=False,
        )

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        path, result = super().lookup_path(path)
        if result is None:
            path, result = super().lookup_path("index.html")

        return (path, result)
