from pathlib import Path
from typing import TYPE_CHECKING

from ceres.__internal__.utilities.platforms import UNIX
from ceres.data import to_json, validate_json
from ceres.directory import Directory

if TYPE_CHECKING:
    from ceres.__internal__.server import CLIServerInfo
    from ceres.config import ConfigMeta


class Project:
    """Represent a Ceres project identified by its configuration file path.

    Provide access to derived paths such as the project directory, a short hash for
    temporary-file naming, and a local-data directory.
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
    def directory_hash(self) -> str:
        from hashlib import sha1

        return sha1(str(self.directory).encode()).hexdigest()[0:6]

    @property
    def local_directory(self) -> Directory:
        return Directory(self.directory / "local")


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
        return _get_temporary_directory() / f"ceres-{self.directory_hash}.server.json"

    @property
    def port(self) -> int | None:
        return self._config.server.port

    def get_cli_server_info(self) -> CLIServerInfo | None:
        """Read and parse the CLI server info file, returning ``None`` on any failure."""
        try:
            from ceres.__internal__.server import CLIServerInfo

            return validate_json(CLIServerInfo, self.cli_server_info_path.read_text())
        except Exception:
            return None

    def write_cli_server_info(self, info: CLIServerInfo) -> None:
        """Serialize `info` to JSON and write it to the CLI server info file (mode 600)."""
        self.cli_server_info_path.touch(0o600)
        self.cli_server_info_path.write_text(to_json(info))
        self.cli_server_info_path.chmod(0o600)

    def delete_cli_server_info(self) -> None:
        """Remove the CLI server info file if it exists."""
        self.cli_server_info_path.unlink(missing_ok=True)


def _get_temporary_directory() -> Path:
    """Return a platform-appropriate temporary directory path.

    Prefer ``/tmp`` on Unix systems when available, falling back to Python's
    ``tempfile.gettempdir``.
    """
    import os

    if UNIX and os.path.isdir("/tmp"):
        return Path("/tmp")

    from tempfile import gettempdir

    return Path(gettempdir())
