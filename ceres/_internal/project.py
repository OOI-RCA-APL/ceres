from __future__ import annotations

from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    from hashlib import sha1
    from pathlib import Path

    from ceres.config import ConfigMeta
    from ceres.directory import Directory


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
    def socket_path(self) -> Path:
        if self._config.server.socket is not None:
            return self._config.server.socket

        return Path(f"/tmp/ceres-{self.directory_hash}.sock")

    @property
    def port(self) -> int | None:
        return self._config.server.port
