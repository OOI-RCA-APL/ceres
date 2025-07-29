from __future__ import annotations

import os
import shutil
from os import PathLike
from pathlib import Path
from tempfile import gettempdir
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Iterable,
    Self,
    TypeAlias,
    Union,
    final,
    overload,
    override,
)

from pydantic_core.core_schema import no_info_after_validator_function

from ceres.data import uuid4

if TYPE_CHECKING:
    from _typeshed import OpenBinaryMode as OpenBinaryMode
    from _typeshed import OpenTextMode as OpenTextMode
    from pydantic import GetCoreSchemaHandler
    from pydantic_core import CoreSchema
else:
    OpenBinaryMode = "OpenBinaryMode"
    OpenTextMode = "OpenTextMode"

StrPath: TypeAlias = str | PathLike[str]
OpenMode: TypeAlias = Union[OpenTextMode, OpenBinaryMode]


@final
class Directory(PathLike[str]):
    def __init__(
        self,
        path: StrPath | None = None,
        parent: Self | None = None,
        temporary: bool | None = None,
    ) -> None:
        if temporary is None:
            temporary = path is None

        if path is not None:
            path = Path(path)
        if parent is not None:
            path = parent.path / (Path(path) if path is not None else "")

        if path is None:
            id = uuid4()
            path = Path(gettempdir()) / f"ceres-directory-{id}.sqlite"
        else:
            path = path.absolute()

        self.__path = path
        self.__parent = parent
        self.__temporary = temporary

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        def validate(value: str | PathLike[str]) -> Self:
            if isinstance(value, cls):
                return value

            return cls(value)

        return no_info_after_validator_function(validate, handler(str | PathLike[str]))

    @property
    def path(self) -> Path:
        return Path(self.__path)

    @property
    def temporary(self) -> bool:
        return self.__temporary

    @override
    def __fspath__(self) -> str:
        return self.__path.__fspath__()

    def __truediv__(self, path: StrPath) -> Path:
        return self.path / path

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(self.__path.__fspath__())})"

    @override
    def __str__(self) -> str:
        return self.__path.__fspath__()

    @override
    def __eq__(self, /, other: object) -> bool:
        return isinstance(other, Directory) and self.path == other.path

    @override
    def __ne__(self, /, other: object) -> bool:
        return not self.__eq__(other)

    def __del__(self) -> None:
        if not self.__temporary:
            return

        try:
            self.remove()
        except Exception:
            pass

    def __resolve(self, path: StrPath | None) -> Path:
        if path is None:
            path = "."
        if not isinstance(path, Path):
            path = Path(path)
        if not path.is_absolute():
            path = self.__path / path
            path = path.absolute()

        return path

    def __setup_write_operation(
        self,
        path: StrPath,
        mkdirs: bool | None,
        mode: OpenMode,
    ) -> Path:
        path = self.__resolve(path)
        if mkdirs is None:
            mkdirs = "w" in mode or "a" in mode
        if mkdirs:
            if not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)

        return path

    @overload
    def open(
        self,
        path: StrPath,
        mode: OpenTextMode = "r",
        buffering: int = ...,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        *,
        mkdirs: bool | None = None,
        **kwargs: Any,
    ) -> IO[str]: ...

    @overload
    def open(
        self,
        path: StrPath,
        mode: OpenBinaryMode,
        buffering: int = ...,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        *,
        mkdirs: bool | None = None,
        **kwargs: Any,
    ) -> IO[bytes]: ...

    def open(
        self,
        path: StrPath,
        mode: OpenMode = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        *,
        mkdirs: bool | None = None,
        **kwargs: Any,
    ) -> IO[str] | IO[bytes]:
        path = self.__setup_write_operation(path, mkdirs, mode)

        return open(
            path,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
            closefd=closefd,
            **kwargs,
        )

    def remove(self, path: StrPath | None = None, *, recursive: bool = True) -> None:
        path = self.__resolve(path)
        if not path.exists():
            return

        if path.is_dir():
            if recursive:
                shutil.rmtree(path)
            else:
                path.rmdir()
        else:
            path.unlink()

    def exists(self, path: StrPath | None = None) -> bool:
        path = self.__resolve(path)
        if path == self.__path:
            return path.is_dir()

        return path.exists()

    def create(self, *, mkdirs: bool = True, exist_ok: bool = True) -> None:
        self.path.mkdir(parents=mkdirs, exist_ok=exist_ok)

    def subpath(self, path: StrPath) -> Path:
        return self.path / path

    def subdir(self, path: StrPath, *, temporary: bool | None = None) -> Self:
        return type(self)(
            path=self.subpath(path),
            parent=self,
            temporary=temporary,
        )

    def iter_subpaths(self, path: StrPath | None = None) -> Iterable[Path]:
        path = self.__resolve(path)
        for name in os.scandir(path):
            yield path / name

    def iter_subdirs(self, path: StrPath | None = None) -> Iterable[Self]:
        for subpath in self.subpaths(path):
            if subpath.is_dir():
                yield self.subdir(subpath)

    def subpaths(self, path: StrPath | None = None) -> list[Path]:
        return list(self.iter_subpaths(path))

    def subdirs(self, path: StrPath | None = None) -> list[Self]:
        return list(self.iter_subdirs(path))

    def touch(self, path: StrPath) -> None:
        path = self.__resolve(path)
        return path.touch(exist_ok=True)

    def move(
        self,
        source: StrPath,
        destination: StrPath,
        *,
        mkdirs: bool | None = None,
    ) -> None:
        source = self.__resolve(source)
        destination = self.__resolve(destination)
        self.__setup_write_operation(destination, mkdirs, "w")
        shutil.move(source, destination)
