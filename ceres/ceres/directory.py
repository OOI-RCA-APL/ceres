from os import PathLike
from pathlib import Path, PurePath
from typing import IO, Any, Literal, final
from uuid import UUID, uuid4

from fs.base import FS
from fs.osfs import OSFS
from fs.tempfs import TempFS
from typing_extensions import Self

OpenMode = Literal["r", "r+", "w", "w+", "a", "a+"]


@final
class Directory(PathLike[str]):
    def __init__(
        self,
        path: PurePath | str | None = None,
        parent: Self | None = None,
    ) -> None:
        if path is not None:
            path = Path(path)
        if parent is not None:
            path = parent.path / (Path(path) if path is not None else "")
        if path is not None:
            path = path.absolute()
            path.mkdir(parents=True, exist_ok=True)

        self.__id = uuid4()
        self.__parent = parent

        if path is not None:
            self.__fs = OSFS(str(path))
        else:
            self.__fs = TempFS()

    @property
    def id(self) -> UUID:
        return self.__id

    @property
    def path(self) -> Path:
        return Path(self.__fs.root_path)

    @property
    def fs(self) -> FS:
        return self.__fs

    def __fspath__(self) -> str:
        return str(self.path)

    def open(
        self,
        path: PurePath | str,
        mode: OpenMode = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str = "",
        mkdirs: bool = True,
        **kwargs: Any,
    ) -> IO[str]:
        if mkdirs:
            parent = str(Path(path).parent)
            if not self.__fs.exists(parent):
                self.__fs.makedirs(parent)

        path = str(path)
        return self.__fs.open(
            path=path,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
            **kwargs,
        )

    def open_binary(
        self,
        path: PurePath | str,
        mode: OpenMode = "r",
        buffering: int = -1,
        mkdirs: bool = True,
        **kwargs: Any,
    ) -> IO[bytes]:
        if mkdirs:
            parent = str(Path(path).parent)
            if not self.__fs.exists(parent):
                self.__fs.makedirs(parent)

        path = str(path)
        return self.__fs.openbin(
            path=path,
            mode=mode,
            buffering=buffering,
            **kwargs,
        )

    def remove(self, path: PurePath | str, recursive: bool = False) -> None:
        path = str(path)
        if self.__fs.isdir(path):
            if recursive:
                self.__fs.removetree(path)
            else:
                self.__fs.remove(path)
        else:
            self.__fs.remove(path)

    def exists(self, path: PurePath | str) -> bool:
        path = str(path)
        return self.__fs.exists(path)

    def is_file(self, path: PurePath | str) -> bool:
        path = str(path)
        return self.__fs.isfile(path)

    def is_dir(self, path: PurePath | str) -> bool:
        path = str(path)
        return self.__fs.isdir(path)

    def is_link(self, path: PurePath | str) -> bool:
        path = str(path)
        return self.__fs.islink(path)

    def is_empty(self, path: PurePath | str) -> bool:
        path = str(path)
        if self.__fs.isdir(path):
            return self.__fs.isempty(path)

        return self.__fs.getsize(path) == 0

    def touch(self, path: PurePath | str) -> None:
        path = str(path)
        self.__fs.touch(path)

    def move(
        self,
        source: PurePath | str,
        destination: PurePath | str,
        *,
        preserve_time: bool = False,
    ) -> None:
        source = str(source)
        destination = str(destination)

        if self.__fs.isdir(source):
            self.__fs.movedir(
                source,
                destination,
                create=True,
                preserve_time=preserve_time,
            )
        else:
            self.__fs.move(
                source,
                destination,
                preserve_time=preserve_time,
            )

    def ls(self, path: PurePath | str = ".") -> list[str]:
        path = str(path)
        return self.__fs.listdir(path)

    def subdir(self, path: PurePath | str) -> Self:
        path = str(path)
        return type(self)(path, self)
