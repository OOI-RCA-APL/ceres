import warnings
from dataclasses import dataclass
from typing import final

from ceres.mount import Mount, MountPath, StrPath

__all__ = [
    "Directory",
    "Files",
]


class Directory(Mount):
    """Deprecated name of `Mount`, kept for one release.

    It carries the name alone, so code calling a removed `Directory` method moves to the
    `Mount` methods with the same step. A value it builds through `/` is a plain `Mount`.
    """

    __slots__ = ()

    def __init__(self, path: StrPath | MountPath | None = None, *, writable: bool | None = None):
        # A `FutureWarning` prints by default, so a project importing a package that builds a
        # `Directory` still learns of the removal.
        warnings.warn("`Directory` is deprecated, use `Mount`.", FutureWarning, stacklevel=2)
        super().__init__(path, writable=writable)


@final
@dataclass(frozen=True, slots=True)
class Files:
    """Marks a component's `Mount` field as a root of the console's file browser.

    Attach it as field metadata, `output: Annotated[Mount, Files("Recordings")]`. A field typed
    `Mount | None` that holds `None` serves no root, and neither does a temporary mount.
    """

    label: str | None = None
    """Name the console shows for the root, the field name when omitted."""

    writable: bool = True
    """Whether callers with OPERATE access or above may change files in the root. `False` keeps
    the root read-only for everyone."""
