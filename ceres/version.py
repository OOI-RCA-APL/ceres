__all__ = [
    "DISTRIBUTIONS",
    "__version__",
]

DISTRIBUTIONS = ("ceres-engine", "ceres")
"""Package names Ceres is distributed under."""


def __get_version() -> str:
    import importlib.metadata

    for distribution in DISTRIBUTIONS:
        try:
            return importlib.metadata.version(distribution)
        except ImportError:
            continue

    # A checkout rather than an install, where no distribution metadata exists at all.
    from pathlib import Path

    try:
        with open(Path(__file__).parent.parent / "pyproject.toml") as file:
            for line in file:
                if not line.startswith("version"):
                    continue

                try:
                    return line.split("=")[1].strip().strip('"')
                except Exception:
                    pass
    except OSError:
        pass

    # Every caller displays this rather than acting on it, so an unreadable version is not
    # worth failing an import over, and this module is imported to run anything at all.
    return "unknown"


__version__ = __get_version()
"""Current Ceres package version as a string."""
