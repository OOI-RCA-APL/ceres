from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from os import PathLike

__all__ = [
    "rel",
    "proj",
]


def rel(path: str | PathLike[str]) -> Path:
    """
    Convert a relative path from the current Python modules's parent directory to an absolute path.

    Args:
        path: A relative path from the current Python file's parent directory.

    Returns:
        The absolute path relative to the parent directory.
    """
    return _get_current_python_module_path() / Path(path)


def proj(relative: str | PathLike | None = None) -> Path:
    """
    Get an absolute path relative to the current Python project's root directory, where the root
    directory is defined as the parent directory of the nearest `pyproject.toml` file in
    the containing directories of the current file.

    If the `relative` parameter is given, the returned path will be the absolute path to the file at the given relative path from the project root. If `relative` is not given, the returned path will be the absolute path to the project root.

    :param relative: The path to the file, relative to the project root.
    :return: The absolute path relative to the project root.
    """
    current = _get_current_python_module_path()
    root = None

    for current in current.parents:
        if (current / "pyproject.toml").is_file():
            root = current
            break

    assert root, (
        "Could not find project root. No parent directory contains a `pyproject.toml` file."
    )
    if relative is not None:
        return root / Path(relative)

    return root


def _get_current_python_module_path() -> Path:
    import inspect

    caller = inspect.stack()[2]
    module = inspect.getmodule(caller[0])
    assert module is not None
    assert module.__file__ is not None
    return Path(module.__file__)
