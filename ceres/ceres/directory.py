from pathlib import Path, PurePath
from typing import IO, Any, Literal
from uuid import UUID, uuid4

from fs.base import FS
from fs.osfs import OSFS
from fs.subfs import SubFS
from fs.tempfs import TempFS
from typing_extensions import Self

OpenMode = Literal["r", "r+", "w", "w+", "a", "a+"]


class Directory:
    def __init__(
        self,
        path: PurePath | str | None = None,
        parent: Self | None = None,
    ) -> None:
        self.__id = uuid4()
        self.__path = Path(path).absolute() if path is not None else None
        if self.__path is not None:
            print(self.__path)
            self.__path.mkdir(parents=True, exist_ok=True)

        if parent is not None:
            self.__fs: FS = SubFS(parent.__fs, str(path) if path is not None else ".")
        elif path is not None:
            self.__fs = OSFS(str(path))
        else:
            self.__fs = TempFS()

    @property
    def id(self) -> UUID:
        return self.__id

    @property
    def path(self) -> Path | None:
        return self.__path

    @property
    def fs(self) -> FS:
        return self.__fs

    def open(
        self,
        path: PurePath | str,
        mode: OpenMode = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str = "",
        **kwargs: Any,
    ) -> IO[str]:
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
        **kwargs: Any,
    ) -> IO[str]:
        path = str(path)
        return self.__fs.open(
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

    def is_dir_empty(self, path: PurePath | str) -> bool:
        path = str(path)
        return self.__fs.isempty(path)

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

    def children(self, path: PurePath | str = ".") -> list[Self]:
        return [Directory(name, self) for name in self.ls(path)]
