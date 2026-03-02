__all__ = [
    "__version__",
]


def __get_version() -> str:
    import importlib.metadata

    try:
        return importlib.metadata.version("ceres")
    except ImportError:
        from pathlib import Path

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
