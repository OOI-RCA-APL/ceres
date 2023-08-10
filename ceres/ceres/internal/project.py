from hashlib import sha1
from pathlib import Path

from ceres.config import Config
from ceres.directory import Directory


class Project:
    def __init__(self, config_path: Path, config: Config) -> None:
        self.__config_path = config_path.resolve()
        self.__config = config

    @property
    def config_path(self) -> Path:
        return self.__config_path

    @property
    def config(self) -> Config:
        return self.__config

    @property
    def directory(self) -> Directory:
        return Directory(self.__config_path.parent)

    @property
    def local_directory(self) -> Directory:
        return Directory(self.directory / "local")

    @property
    def socket_path(self) -> Path:
        return Path(f"/tmp/ceres-{sha1(str(self.directory).encode()).hexdigest()}.sock")

    @property
    def port(self) -> int | None:
        return self.__config.server.port
