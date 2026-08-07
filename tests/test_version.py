import re
from importlib import metadata
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from ceres.version import DISTRIBUTIONS, __version__


def test_version_is_nonempty_string():
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_version_matches_pyproject():
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    expected_version = None

    with open(pyproject_path) as file:
        for line in file:
            if line.startswith("version"):
                expected_version = line.split("=")[1].strip().strip('"')
                break

    assert expected_version is not None
    assert __version__ == expected_version


def test_version_looks_valid():
    assert re.fullmatch(r"\d+(\.\d+)*", __version__)


@pytest.mark.parametrize("installed_as", DISTRIBUTIONS)
def test_version_reads_any_distribution_without_a_checkout(installed_as: str):
    """An installed package has no `pyproject.toml`, so the metadata has to answer alone."""

    def installed(name: str) -> str:
        if name == installed_as:
            return "1.2.3"

        raise metadata.PackageNotFoundError(name)

    with (
        patch("importlib.metadata.version", side_effect=installed),
        patch("builtins.open", side_effect=FileNotFoundError),
    ):
        from ceres.version import __get_version

        assert __get_version() == "1.2.3"


def test_version_is_unknown_when_nothing_is_installed_or_checked_out():
    """Importing this module is a precondition for running anything, so it cannot fail."""
    with (
        patch("importlib.metadata.version", side_effect=metadata.PackageNotFoundError),
        patch("builtins.open", side_effect=FileNotFoundError),
    ):
        from ceres.version import __get_version

        assert __get_version() == "unknown"


def test_version_fallback_path():
    fake_toml = 'version = "1.2.3"\n'

    with (
        patch("importlib.metadata.version", side_effect=ImportError),
        patch("builtins.open", mock_open(read_data=fake_toml)),
    ):
        from ceres.version import __get_version

        result = __get_version()

    assert result == "1.2.3"


def test_version_is_unknown_when_the_checkout_records_none():
    fake_toml = "no-version-here\n"

    with (
        patch("importlib.metadata.version", side_effect=ImportError),
        patch("builtins.open", mock_open(read_data=fake_toml)),
    ):
        from ceres.version import __get_version

        assert __get_version() == "unknown"
