"""Development affordances the CLI offers from a source checkout.

The port assignment decides what address a browser lands on and where the console's dev
server proxies to, so getting it wrong leaves the console pointed at itself.
"""

from pathlib import Path

import pytest

from ceres.__internal__.cli.development import (
    assign_addresses,
    find_console_source,
    is_development_build,
)
from ceres.config import Config
from ceres.data import replace


def test_the_dev_console_takes_the_configured_port() -> None:
    """Without a console port the dev console stands in for the built-in one."""
    config = Config()
    config.server = replace(config.server, port=9000)

    addresses = assign_addresses(config, None)

    assert addresses.console == 9000
    assert addresses.engine != 9000


def test_the_engine_moves_behind_the_dev_console() -> None:
    """The engine binds the port it was moved to, so the section is rewritten."""
    config = Config()
    config.server = replace(config.server, port=9000)

    addresses = assign_addresses(config, None)

    assert config.server.port == addresses.engine


def test_an_unset_port_falls_back_to_the_default() -> None:
    """A configuration naming no port still puts the dev console where the engine would be."""
    config = Config()

    addresses = assign_addresses(config, None)

    assert addresses.console == 8080


def test_a_console_port_serves_both_consoles() -> None:
    """Naming a console port leaves the engine, and its built-in console, where they were."""
    config = Config()
    config.server = replace(config.server, port=9000)

    addresses = assign_addresses(config, 9001)

    assert (addresses.engine, addresses.console) == (9000, 9001)
    assert config.server.port == 9000


def test_the_dev_console_binds_the_engines_host() -> None:
    """Standing in for the built-in console means listening where it would have."""
    config = Config()
    config.server = replace(config.server, host="127.0.0.1")

    assert assign_addresses(config, None).host == "127.0.0.1"


def test_the_console_is_found_in_a_source_tree() -> None:
    """A checkout carries the console beside the package."""
    repository = Path(__file__).parent.parent.parent.parent

    assert find_console_source(repository) == repository / "console"


def test_a_directory_that_is_not_a_source_tree_is_rejected(tmp_path: Path) -> None:
    """A wrong path fails on the spot rather than spawning npm somewhere meaningless."""
    with pytest.raises(ValueError, match="not a Ceres source tree"):
        find_console_source(tmp_path)


def test_a_checkout_is_a_development_build() -> None:
    """The project file beside the package is what tells a checkout from a wheel."""
    assert is_development_build()
