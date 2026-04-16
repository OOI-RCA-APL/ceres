from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from os import PathLike

__all__ = [
    "rel",
    "proj",
]


def rel(path: str | PathLike[str]) -> Path:
    """Resolve a path relative to the calling module's parent directory.

    Args:
        path: Path relative to the calling module's parent directory.

    Returns:
        The absolute path.
    """
    return _get_current_python_module_path() / Path(path)


def proj(relative: str | PathLike | None = None) -> Path:
    """Resolve a path relative to the current Python project's root directory.

    The project root is the parent directory of the nearest `pyproject.toml` file found
    when walking up from the calling module's file. If `relative` is provided, join it
    onto the project root, otherwise return the root itself.

    Args:
        relative: Path relative to the project root, or `None` to return the root.

    Returns:
        The absolute path to the requested location.

    Raises:
        AssertionError: If no parent directory contains a `pyproject.toml` file.
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
