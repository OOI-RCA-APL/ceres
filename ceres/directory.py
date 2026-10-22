import warnings

from ceres.mount import Mount, MountAccessInput, MountPath, StrPath

__all__ = [
    "Directory",
]


class Directory(Mount):
    """Deprecated name of `Mount`, kept for one release.

    It carries the name alone, so code calling a removed `Directory` method moves to the
    `Mount` methods with the same step. A value it builds through `/` is a plain `Mount`.
    """

    __slots__ = ()

    def __init__(
        self,
        path: StrPath | MountPath | None = None,
        *,
        writable: bool | None = None,
        access: MountAccessInput | None = None,
    ):
        # A `FutureWarning` prints by default, so a project importing a package that builds a
        # `Directory` still learns of the removal.
        warnings.warn("`Directory` is deprecated, use `Mount`.", FutureWarning, stacklevel=2)
        super().__init__(path, writable=writable, access=access)
