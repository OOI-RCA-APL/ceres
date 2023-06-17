from hashlib import sha1
from pathlib import Path

from ceres.config import Config


class ProjectContext:
    def __init__(self, config: Config) -> None:
        assert config.path is not None
        self.__path = config.path.parent.resolve()

    @property
    def path(self) -> Path:
        return self.__path

    @property
    def local_path(self) -> Path:
        return self.__path / "local"

    @property
    def hash(self) -> str:
        return sha1(str(self.__path).encode()).hexdigest()

    @property
    def socket(self) -> Path:
        return Path(f"/tmp/ceres-{self.hash}.sock")
