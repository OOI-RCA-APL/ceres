import errno
import os
import shutil
import weakref
from collections.abc import Callable, Iterator, Mapping
from os import PathLike
from pathlib import Path, PurePath
from tempfile import mkdtemp
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    BinaryIO,
    ClassVar,
    Literal,
    NotRequired,
    Self,
    TypedDict,
    overload,
    override,
)

from ceres.concurrency import spawn
from ceres.data import uuid4
from ceres.data.types import OrderedStrEnum
from ceres.paths import PathLayout, PathTemplate, resolve_zone

if TYPE_CHECKING:
    from datetime import datetime

    from _typeshed import OpenBinaryMode, OpenTextMode
    from pydantic import GetCoreSchemaHandler
    from pydantic_core import CoreSchema
    from pydantic_core.core_schema import ValidationInfo

    from ceres.component import MountField

__all__ = [
    "AsyncMount",
    "Mount",
    "MountAccess",
    "MountAccessInput",
    "MountPath",
]

type StrPath = str | PathLike[str]
"""Any value accepted as a filesystem path, either a plain string or a `PathLike`."""


class MountAccess(OrderedStrEnum):
    """What the console and the files API may do with a mount.

    The hierarchy is strict, each level implies every level below it. Access governs callers
    of the API only. A component's own code is limited by `Mount.writable`.
    """

    NONE = "none"
    """The mount is unlisted and every route answers 404."""
    VIEW = "view"
    """Callers may list, preview, and download files."""
    EDIT = "edit"
    """Callers may also upload, rename, move, and delete files."""


MountAccessInput = MountAccess | Literal["none", "view", "edit"]


class MountSetting(TypedDict):
    """A mount written in configuration as a mapping, to set more than its path.

    `server.files.mounts` takes the same mapping, parsed by `RawEngineMountSetting` in the
    `ceres-config` crate, so the two keep the same fields.
    """

    path: StrPath
    access: NotRequired[MountAccessInput]
    layout: NotRequired[str | None]
    zone: NotRequired[str]
    files: NotRequired[Mapping[str, str]]
    """File name templates by kind, see `MountPath.files`. An engine mount takes none, since no
    code writes files into one."""


class _MountFieldReference:
    # Resolves at first use, since `ceres.component` imports this module.
    def __get__(self, instance: object, owner: type) -> type[MountField]:
        from ceres.component import MountField

        return MountField


class MountPath(PathLike[str]):
    """A place inside a mount, the root directory plus a path relative to it.

    `MountPath` holds the pure part shared by `Mount` and `AsyncMount` and never touches the
    filesystem. Joining with `/` stays inside the root, and `parent` stops at the root.
    """

    __slots__ = (
        "_root",
        "_relative",
        "_writable",
        "_access",
        "_temporary",
        "_layout",
        "_zone",
        "_files",
        "_names",
        "_owner",
        "__weakref__",
    )

    _root: Path
    _relative: PurePath
    _writable: bool
    _access: MountAccess | None
    _temporary: bool
    _layout: PathLayout | None
    _zone: str
    _files: Mapping[str, PathTemplate]
    _names: Mapping[str, str]
    _owner: MountPath | None
    """The value carrying a temporary root's finalizer, held so the directory outlives every
    value inside it. `None` on that value itself, since a reference to itself would delay its
    removal to the next garbage collection."""

    if TYPE_CHECKING:
        Field: ClassVar[type[MountField]]
        """Declares a component field holding a mount, see `MountField`."""
    else:
        Field = _MountFieldReference()

    def __init__(
        self,
        path: StrPath | MountPath | None = None,
        *,
        writable: bool | None = None,
        access: MountAccessInput | None = None,
        layout: PathLayout | str | None = None,
        zone: str | None = None,
        files: Mapping[str, PathTemplate | str] | None = None,
    ):
        """Construct a value at `path`.

        Args:
            path: The mount's root directory, a relative path resolving against the current
                directory. A relative path in a configuration file resolves against the
                directory holding the file instead. Another `Mount` or `AsyncMount` converts to
                this type at the same place. `None` creates a temporary directory removed with
                the last value that refers to it, or at interpreter exit.
            writable: Whether the component's own code may change files through this value.
                Defaults to the converted value's setting, `True` otherwise.
            access: Most the files API may do with the mount, see `access`. Defaults to the
                converted value's setting, `None` otherwise.
            layout: Dated folders `dated` writes into and `periods` reads, see `PathLayout`.
                Defaults to the converted value's layout, none otherwise.
            zone: Time zone the layout and file names render in, `utc`, `local`, or an IANA
                name. Defaults to the converted value's zone, `utc` otherwise.
            files: File name templates by kind, see `files`. Each kind given replaces the
                converted value's template of that kind.

        Raises:
            ValueError: If `layout` is not a valid `PathLayout`, a file is not a valid
                `PathTemplate`, or `zone` names no time zone.
        """
        parsed = PathLayout(layout) if isinstance(layout, str) and layout else layout or None
        if zone is not None:
            resolve_zone(zone)

        templates = {
            kind: PathTemplate(template) if isinstance(template, str) else template
            for kind, template in (files or {}).items()
        }
        if isinstance(path, MountPath):
            path._copy_into(self, path._relative)
            if writable is not None:
                self._writable = writable

            if access is not None:
                self._access = MountAccess(access)

            if layout is not None:
                self._layout = parsed

            if zone is not None:
                self._zone = zone

            if templates:
                self._files = {**self._files, **templates}

            return

        self._relative = PurePath()
        self._writable = True if writable is None else writable
        self._access = None if access is None else MountAccess(access)
        self._temporary = path is None
        self._layout = parsed
        self._zone = "utc" if zone is None else zone
        self._files = templates
        self._names = {}
        self._owner = None
        if path is not None:
            self._root = Path(path).absolute()
            return

        self._root = Path(mkdtemp(prefix="ceres-mount-"))
        # The finalizer holds the path string alone, a reference to `self` would keep the
        # owner alive until exit.
        weakref.finalize(self, shutil.rmtree, str(self._root), ignore_errors=True)

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        from pydantic_core.core_schema import (
            dict_schema,
            is_instance_schema,
            nullable_schema,
            plain_serializer_function_ser_schema,
            str_schema,
            typed_dict_field,
            typed_dict_schema,
            union_schema,
            with_info_after_validator_function,
        )

        def validate(value: StrPath | MountSetting, info: ValidationInfo) -> Self:
            setting: MountSetting = value if isinstance(value, dict) else {"path": value}
            given = setting["path"]
            access, layout, zone = setting.get("access"), setting.get("layout"), setting.get("zone")
            files = setting.get("files")
            if isinstance(given, MountPath):
                unchanged = (access, layout, zone, files) == (None, None, None, None)
                if isinstance(given, cls) and unchanged:
                    return given

                return cls(given, access=access, layout=layout, zone=zone, files=files)

            from ceres.project import Project

            # A relative path read from a configuration file resolves beside the file.
            path = Path(given)
            project = Project.from_context(info.context)
            if project is not None and not path.is_absolute():
                path = project.directory.path / path

            return cls(path, access=access, layout=layout, zone=zone, files=files)

        def serialize(value: MountPath) -> str | dict[str, object]:
            setting: dict[str, object] = {"path": str(value)}
            if value._access is not None:
                setting["access"] = value._access.value

            if value._layout is not None:
                setting["layout"] = value._layout.source

            if value._zone != "utc":
                setting["zone"] = value._zone

            if value._files:
                setting["files"] = {kind: file.source for kind, file in value._files.items()}

            return setting if len(setting) > 1 else str(value)

        path = union_schema([is_instance_schema(PathLike), str_schema()])
        # A component field's settle step hands over templates already parsed with its atoms.
        file = union_schema([is_instance_schema(PathTemplate), str_schema()])
        setting = typed_dict_schema(
            {
                "path": typed_dict_field(path),
                "access": typed_dict_field(handler.generate_schema(MountAccess), required=False),
                "layout": typed_dict_field(nullable_schema(str_schema()), required=False),
                "zone": typed_dict_field(str_schema(), required=False),
                "files": typed_dict_field(dict_schema(str_schema(), file), required=False),
            },
            extra_behavior="forbid",
        )
        return with_info_after_validator_function(
            validate,
            union_schema([path, setting]),
            serialization=plain_serializer_function_ser_schema(serialize),
        )

    @property
    def root(self) -> Path:
        """Absolute path of the mount's root directory."""
        return self._root

    @property
    def relative(self) -> PurePath:
        """Path of this value inside the root, empty at the root itself."""
        return self._relative

    @property
    def path(self) -> Path:
        """Absolute path of this value."""
        return self._root / self._relative

    @property
    def name(self) -> str:
        """Final component of the path, the root directory's own name at the root."""
        return self._relative.name or self._root.name

    @property
    def writable(self) -> bool:
        """Whether the component's own code may change files through this value."""
        return self._writable

    @property
    def access(self) -> MountAccess | None:
        """Most the files API may do with the mount, `None` to follow `writable`.

        A `None` value allows `MountAccess.EDIT` on a writable mount and `MountAccess.VIEW` on
        a read-only one. The server's `server.files.access` cap and each caller's access level
        on the component lower it further.
        """
        return self._access

    @property
    def temporary(self) -> bool:
        """Whether the root is a temporary directory removed with its last reference."""
        return self._temporary

    @property
    def layout(self) -> PathLayout | None:
        """Dated folders `dated` writes into and `periods` reads, `None` for none."""
        return self._layout

    @property
    def zone(self) -> str:
        """Time zone the layout and file names render in, `utc`, `local`, or an IANA name."""
        return self._zone

    @property
    def files(self) -> Mapping[str, PathTemplate]:
        """File name templates by kind, each naming one kind of file `file` writes into the
        layout's folders, such as `{"still": "{datetime}.jpg"}`.

        A template may hold folders of its own, so kinds sharing a mount can keep apart.
        """
        return self._files

    @property
    def names(self) -> Mapping[str, str]:
        """Values of the name atoms, `{component}`, `{mount}`, and `{project}`, that the
        layout and file names render.

        A component fills them in for each mount field it lists, a mount built in code has none.
        """
        return self._names

    def render(
        self,
        template: PathTemplate,
        when: datetime,
        values: Mapping[str, object] | None = None,
    ) -> str:
        """Render `template` for `when` in the mount's zone, with its names and `values`.

        Raises:
            ValueError: See `PathTemplate.render`.
        """
        names = self._names if values is None else {**self._names, **values}
        return template.render(when, self._zone, names)

    def _join(self, part: StrPath) -> PurePath:
        """Return `relative` joined with `part`, the shared rule behind `/` on each value type.

        `part` may hold several segments separated by `/`. A `.` segment is dropped.

        Raises:
            ValueError: If `part` is absolute or ends in a separator, or a segment is empty,
                `..`, or holds a backslash or NUL character.
        """
        text = os.fspath(part)
        if PurePath(text).anchor or text.startswith(("/", "\\")):
            raise ValueError(f"path '{text}' is absolute, a mount joins only relative paths")

        separators = "/" if os.sep == "/" else "/" + os.sep
        if text.endswith(tuple(separators)):
            raise ValueError(f"path '{text}' ends in a separator, a mount joins only names")

        relative = self._relative
        for segment in _split(text, separators):
            if segment == ".":
                continue

            if segment in ("", "..") or "\\" in segment or "\0" in segment:
                raise ValueError(f"path '{text}' has an invalid segment '{segment}'")

            relative /= segment

        return relative

    @override
    def __fspath__(self) -> str:
        return os.fspath(self.path)

    @override
    def __str__(self) -> str:
        return os.fspath(self.path)

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({os.fspath(self.path)!r})"

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MountPath):
            return NotImplemented

        return (self._root, self._relative) == (other._root, other._relative)

    @override
    def __hash__(self) -> int:
        return hash((self._root, self._relative))

    def _at[M: MountPath](self, kind: type[M], relative: PurePath) -> M:
        # Skips `__init__`, so a deprecated subclass warns once, at the value the caller built.
        value = object.__new__(kind)
        self._copy_into(value, relative)
        return value

    def _replace[M: MountPath](self: M, *, writable: bool, access: MountAccess | None) -> M:
        value = self._at(type(self), self._relative)
        value._writable = writable
        value._access = access
        return value

    def _named[M: MountPath](self: M, names: Mapping[str, str]) -> M:
        value = self._at(type(self), self._relative)
        value._names = names
        return value

    def _file(self, kind: str | PathTemplate) -> PathTemplate:
        if isinstance(kind, PathTemplate):
            return kind

        try:
            return self._files[kind]
        except KeyError:
            raise ValueError(f"mount has no file '{kind}'") from None

    def _copy_into(self, value: MountPath, relative: PurePath) -> None:
        value._root = self._root
        value._relative = relative
        value._writable = self._writable
        value._access = self._access
        value._temporary = self._temporary
        value._layout = self._layout
        value._zone = self._zone
        value._files = self._files
        value._names = self._names
        value._owner = self._owner if self._owner is not None or not self._temporary else self

    def _require_writable(self) -> None:
        if not self._writable:
            raise PermissionError(f"mount '{self._root}' is read-only")

    def _check_inside(self, other: MountPath) -> None:
        if other._root != self._root:
            raise ValueError(f"'{other}' lies outside the mount '{self._root}'")


class Mount(MountPath):
    """A directory a component owns or reads, with synchronous file operations.

    Each method mirrors its `pathlib.Path` namesake and acts on `path`. Every value a method
    returns stays inside the root. A symlink inside a mount is followed, the files API refuses
    one that leaves the mount.
    """

    __slots__ = ()

    def __truediv__(self, part: StrPath) -> Mount:
        """Return the value at `part` below this one, see `MountPath._join`."""
        return self._at(Mount, self._join(part))

    @property
    def parent(self) -> Mount:
        """Value one level up, the root itself at the root."""
        return self._at(Mount, self._relative.parent)

    def exists(self) -> bool:
        """Whether the path exists."""
        return self.path.exists()

    def is_file(self) -> bool:
        """Whether the path is a regular file."""
        return self.path.is_file()

    def is_dir(self) -> bool:
        """Whether the path is a directory."""
        return self.path.is_dir()

    def stat(self) -> os.stat_result:
        """Return the path's status, following a symlink."""
        return self.path.stat()

    def iterdir(self) -> Iterator[Mount]:
        """Yield the entries of this directory, in filesystem order."""
        # A listed name is taken as the filesystem gives it, `/` would refuse a backslash.
        for entry in self.path.iterdir():
            yield self._at(Mount, self._relative / entry.name)

    def glob(self, pattern: str) -> Iterator[Mount]:
        """Yield the entries below this directory matching `pattern`.

        Raises:
            ValueError: If `pattern` is absolute or holds a `..` segment.
        """
        if PurePath(pattern).anchor or ".." in _split(pattern, "/\\"):
            raise ValueError(f"pattern '{pattern}' leaves the mount")

        for match in self.path.glob(pattern):
            yield self._at(Mount, PurePath(match.relative_to(self._root)))

    def read_bytes(self) -> bytes:
        """Return the file's contents."""
        return self.path.read_bytes()

    def read_text(self, encoding: str | None = None, errors: str | None = None) -> str:
        """Return the file's contents decoded as text."""
        return self.path.read_text(encoding=encoding, errors=errors)

    @overload
    def open(
        self,
        mode: OpenTextMode = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[str]: ...

    @overload
    def open(
        self,
        mode: OpenBinaryMode,
        buffering: int = -1,
        encoding: None = None,
        errors: None = None,
        newline: None = None,
    ) -> IO[bytes]: ...

    def open(
        self,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[Any]:
        """Open the file, as the built-in `open` does.

        Raises:
            PermissionError: If `mode` writes and the mount is read-only.
        """
        if any(flag in mode for flag in "wax+"):
            self._require_writable()

        return open(
            self.path,
            mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )

    def mkdir(self, parents: bool = True, exist_ok: bool = True) -> None:
        """Create this directory, and its missing parents by default."""
        self._require_writable()
        self.path.mkdir(parents=parents, exist_ok=exist_ok)

    def write_bytes(self, data: bytes) -> None:
        """Replace the file's contents with `data`, in place."""
        self._require_writable()
        self.path.write_bytes(data)

    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> None:
        """Replace the file's contents with `data` encoded as text, in place."""
        self._require_writable()
        self.path.write_text(data, encoding=encoding, errors=errors, newline=newline)

    def unlink(self, missing_ok: bool = False) -> None:
        """Remove the file."""
        self._require_writable()
        self.path.unlink(missing_ok=missing_ok)

    def rmdir(self) -> None:
        """Remove the directory, which must be empty."""
        self._require_writable()
        self.path.rmdir()

    def rmtree(self) -> None:
        """Remove the directory and everything below it."""
        self._require_writable()
        shutil.rmtree(self.path)

    def rename(self, target: MountPath) -> Mount:
        """Move this entry to `target` in the same mount, replacing a file there on POSIX.

        Raises:
            ValueError: If `target` lies in another mount.
        """
        self._require_writable()
        self._check_inside(target)
        self.path.rename(target.path)
        return Mount(target)

    def replace(self, target: MountPath) -> Mount:
        """Move this entry to `target` in the same mount, replacing a file there.

        Raises:
            ValueError: If `target` lies in another mount.
        """
        self._require_writable()
        self._check_inside(target)
        self.path.replace(target.path)
        return Mount(target)

    def create(self, name: StrPath, data: bytes | Callable[[BinaryIO], object]) -> Mount:
        """Write a new file at `name` below this directory, so it appears whole or not at all.

        The data goes to a hidden part file beside the target, reaches the disk, and then
        takes the target's name. Missing parent directories are created.

        Args:
            name: Path of the new file relative to this value.
            data: The file's contents, or a function writing them to the open part file.

        Returns:
            The new file.

        Raises:
            FileExistsError: If the target exists, which is never replaced.
            PermissionError: If the mount is read-only.
        """
        self._require_writable()
        target = self / name
        target.path.parent.mkdir(parents=True, exist_ok=True)
        part = target.path.with_name(f".{target.name}.{uuid4().hex}.part")
        try:
            with open(part, "xb") as stream:
                if callable(data):
                    data(stream)
                else:
                    stream.write(data)

                stream.flush()
                os.fsync(stream.fileno())

            _rename_without_replacing(part, target.path)
        except BaseException:
            part.unlink(missing_ok=True)
            raise

        return target

    def append(self, name: StrPath, data: bytes) -> Mount:
        """Append `data` to the file at `name` below this directory, creating it if missing.

        Missing parent directories are created.

        Returns:
            The file.

        Raises:
            PermissionError: If the mount is read-only.
        """
        self._require_writable()
        target = self / name
        target.path.parent.mkdir(parents=True, exist_ok=True)
        with open(target.path, "ab") as stream:
            stream.write(data)

        return target

    def dated(self, when: datetime) -> Mount:
        """Return the layout's folder for `when` below this value, creating it.

        Returns:
            The folder, or this value when the mount has no layout.

        Raises:
            ValueError: If `when` is naive or a name atom has no value.
            PermissionError: If the folder is missing and the mount is read-only.
        """
        if self._layout is None:
            return self

        folder = self / self.render(self._layout, when)
        # A read-only mount may still read a folder that exists, which `mkdir` would refuse.
        if not folder.is_dir():
            folder.mkdir()

        return folder

    def file(
        self,
        kind: str | PathTemplate,
        when: datetime,
        values: Mapping[str, object] | None = None,
    ) -> Mount:
        """Return the path a new file of `kind` takes for `when`, creating its folder.

        One time renders both the layout's folder and the file's name, so a file written at
        midnight never takes one day's name in the next day's folder.

        Args:
            kind: A kind `files` names, or a `PathTemplate` for a one-off file.
            when: The time the file is for, timezone-aware.
            values: Values for the template's atoms beyond the mount's names.

        Raises:
            ValueError: If `files` names no such kind, `when` is naive, an atom has no value,
                or the name renders outside the mount.
            PermissionError: If the mount is read-only.
        """
        target = self.dated(when) / self.render(self._file(kind), when, values)
        target.parent.mkdir()
        return target

    def periods(self, after: datetime, before: datetime) -> Iterator[Mount]:
        """Yield each existing layout folder below this value whose period overlaps the range.

        Folders come in time order, see `PathLayout.walk`. A mount without a layout yields
        itself when it exists.

        Args:
            after: Start of the range, inclusive, timezone-aware.
            before: End of the range, exclusive, timezone-aware.
        """
        if self._layout is None:
            if self.is_dir():
                yield self

            return

        for folder in self._layout.walk(self.path, after, before, self._zone, self._names):
            yield self._at(Mount, PurePath(folder.relative_to(self._root)))


class AsyncMount(MountPath):
    """A directory a component owns or reads, with file operations run on a worker thread.

    Each method awaits its `Mount` namesake through `spawn`, so a slow disk never blocks the
    event loop. `AsyncMount(mount)` and `Mount(async_mount)` convert at the same place.
    """

    __slots__ = ()

    def __truediv__(self, part: StrPath) -> AsyncMount:
        """Return the value at `part` below this one, see `MountPath._join`."""
        return self._at(AsyncMount, self._join(part))

    @property
    def parent(self) -> AsyncMount:
        """Value one level up, the root itself at the root."""
        return self._at(AsyncMount, self._relative.parent)

    async def exists(self) -> bool:
        """Whether the path exists."""
        return await spawn(Mount(self).exists)

    async def is_file(self) -> bool:
        """Whether the path is a regular file."""
        return await spawn(Mount(self).is_file)

    async def is_dir(self) -> bool:
        """Whether the path is a directory."""
        return await spawn(Mount(self).is_dir)

    async def stat(self) -> os.stat_result:
        """Return the path's status, following a symlink."""
        return await spawn(Mount(self).stat)

    async def iterdir(self) -> list[AsyncMount]:
        """Return the entries of this directory, in filesystem order."""
        entries = await spawn(lambda: list(Mount(self).iterdir()))
        return [AsyncMount(entry) for entry in entries]

    async def glob(self, pattern: str) -> list[AsyncMount]:
        """Return the entries below this directory matching `pattern`, see `Mount.glob`."""
        matches = await spawn(lambda: list(Mount(self).glob(pattern)))
        return [AsyncMount(match) for match in matches]

    async def read_bytes(self) -> bytes:
        """Return the file's contents."""
        return await spawn(Mount(self).read_bytes)

    async def read_text(self, encoding: str | None = None, errors: str | None = None) -> str:
        """Return the file's contents decoded as text."""
        return await spawn(Mount(self).read_text, encoding, errors)

    async def mkdir(self, parents: bool = True, exist_ok: bool = True) -> None:
        """Create this directory, and its missing parents by default."""
        await spawn(Mount(self).mkdir, parents, exist_ok)

    async def write_bytes(self, data: bytes) -> None:
        """Replace the file's contents with `data`, in place."""
        await spawn(Mount(self).write_bytes, data)

    async def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> None:
        """Replace the file's contents with `data` encoded as text, in place."""
        await spawn(Mount(self).write_text, data, encoding, errors, newline)

    async def unlink(self, missing_ok: bool = False) -> None:
        """Remove the file."""
        await spawn(Mount(self).unlink, missing_ok)

    async def rmdir(self) -> None:
        """Remove the directory, which must be empty."""
        await spawn(Mount(self).rmdir)

    async def rmtree(self) -> None:
        """Remove the directory and everything below it."""
        await spawn(Mount(self).rmtree)

    async def rename(self, target: MountPath) -> AsyncMount:
        """Move this entry to `target` in the same mount, see `Mount.rename`."""
        return AsyncMount(await spawn(Mount(self).rename, target))

    async def replace(self, target: MountPath) -> AsyncMount:
        """Move this entry to `target` in the same mount, see `Mount.replace`."""
        return AsyncMount(await spawn(Mount(self).replace, target))

    async def create(
        self,
        name: StrPath,
        data: bytes | Callable[[BinaryIO], object],
    ) -> AsyncMount:
        """Write a new file at `name` whole or not at all, see `Mount.create`.

        A `data` function runs on the worker thread.
        """
        return AsyncMount(await spawn(Mount(self).create, name, data))

    async def append(self, name: StrPath, data: bytes) -> AsyncMount:
        """Append `data` to the file at `name`, see `Mount.append`."""
        return AsyncMount(await spawn(Mount(self).append, name, data))

    async def dated(self, when: datetime) -> AsyncMount:
        """Return the layout's folder for `when`, creating it, see `Mount.dated`."""
        return AsyncMount(await spawn(Mount(self).dated, when))

    async def file(
        self,
        kind: str | PathTemplate,
        when: datetime,
        values: Mapping[str, object] | None = None,
    ) -> AsyncMount:
        """Return the path a new file of `kind` takes for `when`, see `Mount.file`."""
        return AsyncMount(await spawn(Mount(self).file, kind, when, values))

    async def periods(self, after: datetime, before: datetime) -> list[AsyncMount]:
        """Return the layout folders whose period overlaps the range, see `Mount.periods`."""
        folders = await spawn(lambda: list(Mount(self).periods(after, before)))
        return [AsyncMount(folder) for folder in folders]


def _split(text: str, separators: str) -> list[str]:
    segments = [text]
    for separator in separators:
        segments = [piece for segment in segments for piece in segment.split(separator)]

    return segments


def _rename_without_replacing(source: Path, target: Path) -> None:
    """Move `source` to `target`, failing with `FileExistsError` when `target` exists.

    Windows never replaces on rename. A POSIX filesystem without hard links falls back to a
    check before the rename, so a file created between the two is replaced.
    """
    if os.name == "nt":
        os.rename(source, target)
        return

    try:
        os.link(source, target)
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS):
            raise

        if target.exists():
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(target))

        os.rename(source, target)
        return

    os.unlink(source)
