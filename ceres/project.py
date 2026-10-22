from collections.abc import Mapping
from typing import TYPE_CHECKING, override

from ceres.mount import Mount

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "STATE_DIRECTORY",
    "Project",
]

STATE_DIRECTORY = ".ceres"
"""Name of the directory in a project that holds what Ceres writes for itself."""


class Project:
    """A Ceres project, identified by the path of its configuration file.

    Reading a configuration file passes its project to validation under the context key
    `"project"`, so a relative `Mount` path in the file resolves against `directory`.
    """

    __slots__ = ("_config_path",)

    def __init__(self, config_path: Path) -> None:
        # Lexical like `Mount`, so `directory` equals a `Mount` built from the same path even
        # under a symbolic link.
        self._config_path = config_path.absolute()

    @classmethod
    def from_context(cls, context: object) -> Project | None:
        """Answer the project a validation `context` carries, `None` when it carries none."""
        if not isinstance(context, Mapping):
            return None

        project = context.get("project")
        return project if isinstance(project, Project) else None

    @property
    def config_path(self) -> Path:
        """Absolute path of the configuration file."""
        return self._config_path

    @property
    def directory(self) -> Mount:
        """The directory holding the configuration file."""
        return Mount(self._config_path.parent)

    @property
    def state_directory(self) -> Path:
        """The `.ceres` directory, holding runtime state and generated TLS material."""
        return self._config_path.parent / STATE_DIRECTORY

    def create_state_directory(self) -> Path:
        """Create the `.ceres` directory if needed, answering its path.

        It ignores itself through its own `.gitignore`, so nothing in it reaches version
        control whatever the project's own ignore rules say.
        """
        directory = self.state_directory
        directory.mkdir(parents=True, exist_ok=True)
        ignore = directory / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n")

        return directory

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Project):
            return NotImplemented

        return self._config_path == other._config_path

    @override
    def __hash__(self) -> int:
        return hash(self._config_path)

    @override
    def __repr__(self) -> str:
        return f"Project({str(self._config_path)!r})"
