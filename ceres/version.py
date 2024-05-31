from __future__ import annotations


def __get_version() -> str:
    import importlib.metadata
    from pathlib import Path

    try:
        return importlib.metadata.version("ceres")
    except ImportError:
        with open(Path(__file__).parent.parent / "pyproject.toml") as file:
            for line in file:
                if not line.startswith("version"):
                    continue

                try:
                    return line.split("=")[1].strip().strip('"')
                except Exception:
                    pass

    raise RuntimeError("Unable to determine package version.")


__version__ = __get_version()
"""
The current Ceres version number as a string.
"""
