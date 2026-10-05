from typing import TYPE_CHECKING

from ceres.data import to_json, validate_json
from ceres.directory import Directory

if TYPE_CHECKING:
    from pathlib import Path

    from ceres.__internal__.server import CLIServerInfo
    from ceres.config import ConfigMeta


STATE_DIRECTORY = ".ceres"
"""Name of the directory in a project that holds what Ceres writes for itself."""


class Project:
    """Represent a Ceres project identified by its configuration file path.

    Provide access to derived paths such as the project directory and the `.ceres` state
    directory beside the configuration.
    """

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path.resolve()

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def directory(self) -> Directory:
        return Directory(self._config_path.parent)

    @property
    def state_directory(self) -> Path:
        """The `.ceres` directory, holding runtime state and generated TLS material."""
        return self.directory / STATE_DIRECTORY

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


class LoadedProject(Project):
    """A ``Project`` whose configuration has been parsed and loaded into memory.

    Extend the base ``Project`` with server-info management (reading, writing, and deleting
    the CLI server info file used to communicate with a running Ceres server).
    """

    def __init__(self, config_path: Path, config: ConfigMeta) -> None:
        super().__init__(config_path)
        self._config = config

    @property
    def config(self) -> ConfigMeta:
        return self._config

    @property
    def cli_server_info_path(self) -> Path:
        return self.state_directory / "server.json"

    def get_cli_server_info(self) -> CLIServerInfo | None:
        """Read and parse the CLI server info file, returning ``None`` on any failure."""
        try:
            from ceres.__internal__.server import CLIServerInfo

            return validate_json(CLIServerInfo, self.cli_server_info_path.read_text())
        except Exception:
            return None

    def write_cli_server_info(self, info: CLIServerInfo) -> None:
        """Serialize `info` to JSON and write it to the CLI server info file (mode 600).

        The file carries the CLI server's token, so it is created owner-only rather than
        narrowed after the token is already in it.
        """
        import os

        self.create_state_directory()
        path = self.cli_server_info_path
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(to_json(info))

        # A file left by an earlier run keeps its mode through `O_CREAT`.
        path.chmod(0o600)

    def delete_cli_server_info(self) -> None:
        """Remove the CLI server info file if it exists."""
        self.cli_server_info_path.unlink(missing_ok=True)
