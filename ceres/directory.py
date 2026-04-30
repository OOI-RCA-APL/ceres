import os
import shutil
from collections.abc import Iterable
from os import PathLike
from pathlib import Path
from tempfile import gettempdir
from typing import IO, TYPE_CHECKING, Any, Self, final, overload, override

from ceres.data import uuid4

if TYPE_CHECKING:
    from _typeshed import OpenBinaryMode as OpenBinaryMode
    from _typeshed import OpenTextMode as OpenTextMode
    from pydantic import GetCoreSchemaHandler
    from pydantic_core import CoreSchema

__all__ = [
    "Directory",
]

type StrPath = str | PathLike[str]
"""Any value accepted as a filesystem path, either a plain string or a `PathLike`."""

type OpenMode = OpenTextMode | OpenBinaryMode
"""Mode string passed to `open`, covering both text and binary variants."""


@final
class Directory(PathLike[str]):
    """A filesystem directory handle with helpers for reading, writing, and traversing contents.

    `Directory` resolves child paths relative to its base path and exposes helpers for common
    filesystem operations. Directories can be marked `temporary`, in which case they are removed
    when the handle is garbage collected.
    """

    __slots__ = (
        "_path",
        "_parent",
        "_temporary",
    )

    def __init__(
        self,
        path: StrPath | None = None,
        parent: Self | None = None,
        temporary: bool | None = None,
    ) -> None:
        """Construct a directory handle rooted at `path`.

        Args:
            path: Absolute or relative path to the directory. When `parent` is provided,
                `path` is resolved relative to it. When `None`, a unique temporary path is
                generated under the system temp directory.
            parent: Optional parent `Directory`, used for resolving `path` and recorded for
                reference.
            temporary: When `True`, remove the directory in `__del__`. Defaults to `True`
                when `path` is `None`, and `False` otherwise.
        """
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

        self._path = path
        self._parent = parent
        self._temporary = temporary

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        from pydantic_core.core_schema import no_info_after_validator_function

        def validate(value: str | PathLike[str]) -> Self:
            if isinstance(value, cls):
                return value

            return cls(value)

        return no_info_after_validator_function(validate, handler(str | PathLike[str]))

    @property
    def path(self) -> Path:
        """Absolute `Path` to the directory."""
        return Path(self._path)

    @property
    def temporary(self) -> bool:
        """Whether the directory is removed when this handle is garbage collected."""
        return self._temporary

    @override
    def __fspath__(self) -> str:
        return self._path.__fspath__()

    def __truediv__(self, path: StrPath) -> Path:
        return self.path / path

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(self._path.__fspath__())})"

    @override
    def __str__(self) -> str:
        return self._path.__fspath__()

    @override
    def __eq__(self, /, other: object) -> bool:
        return isinstance(other, Directory) and self.path == other.path

    @override
    def __ne__(self, /, other: object) -> bool:
        return not self.__eq__(other)

    def __del__(self) -> None:
        if not self._temporary:
            return

        try:
            self.remove()
        except Exception:
            pass

    def _resolve(self, path: StrPath | None) -> Path:
        if path is None:
            path = "."
        if not isinstance(path, Path):
            path = Path(path)
        if not path.is_absolute():
            path = self._path / path
            path = path.absolute()

        return path

    def _setup_write_operation(
        self,
        path: StrPath,
        mkdirs: bool | None,
        mode: OpenMode,
    ) -> Path:
        path = self._resolve(path)
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
        """Open a file inside the directory, creating parent directories on demand.

        Args:
            path: Path relative to this directory, or an absolute path.
            mode: Open mode string passed to `open`.
            buffering: Buffering policy passed to `open`.
            encoding: Text encoding passed to `open`.
            errors: Error handler name passed to `open`.
            newline: Newline handling passed to `open`.
            closefd: Whether `open` should close the underlying file descriptor.
            mkdirs: When `True`, ensure the parent directory exists. Defaults to `True` when the
                mode is write or append, `False` otherwise.
            **kwargs: Additional keyword arguments forwarded to `open`.

        Returns:
            The opened file object, matching the mode's text or binary variant.
        """
        path = self._setup_write_operation(path, mkdirs, mode)

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
        """Remove a file or directory.

        Args:
            path: Path relative to this directory, an absolute path, or `None` to remove
                this directory itself.
            recursive: When removing a directory, delete its contents too. Has no effect
                when removing a file.
        """
        path = self._resolve(path)
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
        """Return whether the given path exists.

        Args:
            path: Path relative to this directory, an absolute path, or `None` to check
                whether this directory itself exists.

        Returns:
            `True` if the path exists. When checking this directory itself, the path must
            be a directory, not a file.
        """
        path = self._resolve(path)
        if path == self._path:
            return path.is_dir()

        return path.exists()

    def create(self, *, mkdirs: bool = True, exist_ok: bool = True) -> None:
        """Create this directory on disk.

        Args:
            mkdirs: When `True`, create intermediate parent directories as needed.
            exist_ok: When `True`, silently succeed if the directory already exists.
        """
        self.path.mkdir(parents=mkdirs, exist_ok=exist_ok)

    def subpath(self, path: StrPath) -> Path:
        """Return the absolute `Path` obtained by joining `path` onto this directory."""
        return self.path / path

    def subdir(self, path: StrPath, *, temporary: bool | None = None) -> Self:
        """Return a child `Directory` rooted at `path` relative to this directory.

        Args:
            path: Relative path to the child directory.
            temporary: Forwarded to the child `Directory`, see `Directory.__init__`.

        Returns:
            A new `Directory` whose parent is this one.
        """
        return type(self)(
            path=self.subpath(path),
            parent=self,
            temporary=temporary,
        )

    def iter_subpaths(self, path: StrPath | None = None) -> Iterable[Path]:
        """Yield absolute paths for each entry directly inside `path`.

        Args:
            path: Path relative to this directory, an absolute path, or `None` to list this
                directory itself.

        Yields:
            Absolute paths for each direct child entry, in filesystem order.
        """
        path = self._resolve(path)
        for name in os.scandir(path):
            yield path / name

    def iter_subdirs(self, path: StrPath | None = None) -> Iterable[Self]:
        """Yield child `Directory` handles for each subdirectory directly inside `path`.

        Args:
            path: Path relative to this directory, an absolute path, or `None` to list this
                directory itself.

        Yields:
            `Directory` handles for each direct child that is a directory.
        """
        for subpath in self.subpaths(path):
            if subpath.is_dir():
                yield self.subdir(subpath)

    def subpaths(self, path: StrPath | None = None) -> list[Path]:
        """Return the list of direct child paths under `path`, see `iter_subpaths`."""
        return list(self.iter_subpaths(path))

    def subdirs(self, path: StrPath | None = None) -> list[Self]:
        """Return the list of direct child directories under `path`, see `iter_subdirs`."""
        return list(self.iter_subdirs(path))

    def touch(self, path: StrPath) -> None:
        """Ensure the file at `path` exists, creating an empty file if needed.

        Args:
            path: Path relative to this directory, or an absolute path.
        """
        path = self._resolve(path)
        return path.touch(exist_ok=True)

    def move(
        self,
        source: StrPath,
        destination: StrPath,
        *,
        mkdirs: bool | None = None,
    ) -> None:
        """Move a file or directory from `source` to `destination`.

        Args:
            source: Source path relative to this directory, or an absolute path.
            destination: Destination path relative to this directory, or an absolute path.
            mkdirs: When `True`, ensure the destination's parent directory exists. Defaults
                to `True`.
        """
        source = self._resolve(source)
        destination = self._resolve(destination)
        self._setup_write_operation(destination, mkdirs, "w")
        shutil.move(source, destination)
