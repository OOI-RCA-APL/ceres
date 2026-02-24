from __future__ import annotations

from typing import TYPE_CHECKING

from ceres._internal import util
from ceres.data import to_json, validate_json
from ceres.directory import Directory

if TYPE_CHECKING:
    from pathlib import Path

    from ceres._internal.server import CLIServerInfo
    from ceres.config import ConfigMeta


class Project:
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
    def __init__(self, config_path: Path, config: ConfigMeta) -> None:
        super().__init__(config_path)
        self._config = config

    @property
    def config(self) -> ConfigMeta:
        return self._config

    @property
    def cli_server_info_path(self) -> Path:
        return util.get_temporary_directory() / f"ceres-{self.directory_hash}.server.json"

    @property
    def port(self) -> int | None:
        return self._config.server.port

    def get_cli_server_info(self) -> CLIServerInfo | None:
        try:
            from ceres._internal.server import CLIServerInfo

            return validate_json(self.cli_server_info_path.read_text(), CLIServerInfo)
        except Exception:
            return None

    def write_cli_server_info(self, info: CLIServerInfo) -> None:
        self.cli_server_info_path.touch(0o600)
        self.cli_server_info_path.write_text(to_json(info))
        self.cli_server_info_path.chmod(0o600)

    def delete_cli_server_info(self) -> None:
        self.cli_server_info_path.unlink(missing_ok=True)
