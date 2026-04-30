from pathlib import Path
from typing import TYPE_CHECKING, override

from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    import os


class ConsoleFiles(StaticFiles):
    """Serve the built console SPA assets, falling back to `index.html` for client-side routing."""

    def __init__(self) -> None:
        """Create the static-files mount pointed at the pre-built console directory."""
        directory = Path(__file__).parent / "../../static/console"
        directory = directory.resolve()
        directory.mkdir(mode=755, parents=True, exist_ok=True)
        super().__init__(directory=directory, html=True)

    @override
    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        """Look up a static file by path, falling back to `index.html` when no match is found.

        Args:
            path: The URL path segment to resolve against the console directory.

        Returns:
            A tuple of the resolved filesystem path and its stat result, or the `index.html`
            fallback if the requested path does not exist.
        """
        path, result = super().lookup_path(path)
        if result is None:
            path, result = super().lookup_path("index.html")

        return (path, result)
