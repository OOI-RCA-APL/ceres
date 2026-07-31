"""Filters the CLI builds from a command's fields.

A command names only the fields its invocation mentioned, and the conversion into a
filter has to carry that set-ness through rather than dumping the command whole. Models
that read set-ness as a sentinel depend on it, and a variable's `value` is one, where
"unmentioned" and "explicitly null" mean different things.
"""

from typing import TYPE_CHECKING

from pydantic import create_model
from pydantic_settings import CliSubCommand

from ceres import Engine
from ceres.__internal__.cli.main import BaseMainCommand
from ceres.__internal__.cli.shared import (
    create_entity_count_command,
    create_entity_select_command,
)
from ceres.address import Address
from ceres.config import Config
from ceres.data import validate
from ceres.variable import Variable

if TYPE_CHECKING:
    from pathlib import Path


def _invoke[T](Command: type[T], *arguments: str) -> T:
    """Build one command the way an invocation would, nested under the main command.

    The main command is the settings root, and a root reports every one of its fields
    set whatever the invocation named. A leaf built directly as its own root would
    inherit that and report a set-ness no invocation gave it.
    """
    Main = create_model(
        "MainCommand",
        variables=(CliSubCommand[Command], ...),
        __base__=BaseMainCommand,
        __doc__="Ceres",
    )
    main = Main(["variables", *arguments, "--no-color"])
    # The field is declared at runtime, so it reaches through `getattr` rather than as
    # an attribute the checker can see on the generated class.
    return getattr(main, "variables")


async def _build_project(tmp_path: Path) -> Engine:
    """Write a project config on a file-backed database and store a few variables."""
    (tmp_path / "ceres.yaml").write_text(
        "components: []\ndatabase:\n  type: sqlite\n  path: records.sqlite\n"
    )
    engine = Engine()
    await engine.load(
        validate(
            Config,
            {
                "components": [],
                "database": {"type": "sqlite", "path": str(tmp_path / "records.sqlite")},
            },
        ),
        checks=(),
    )
    await engine.database.migrate()
    await engine.variables.create(
        Variable.Create(address=Address("@a"), name="__enabled__", value=True)
    )
    await engine.variables.create(Variable.Create(address=Address("@b"), name="x", value=5))
    await engine.variables.create(Variable.Create(address=Address("@c"), name="y", value=None))
    return engine


def test_an_unmentioned_field_reaches_the_filter_unset() -> None:
    """A field the invocation never named leaves no constraint behind."""
    Command = create_entity_select_command(Variable)

    assert _invoke(Command).read(Variable.Filter).model_fields_set == set()
    assert _invoke(Command, "--name", "x").read(Variable.Filter).model_fields_set == {"name"}


async def test_an_unfiltered_select_matches_every_variable(tmp_path: Path) -> None:
    """A bare select is unconstrained, which a set-ness sentinel read wrongly would not be."""
    engine = await _build_project(tmp_path)
    Command = create_entity_select_command(Variable)
    command = _invoke(Command, "--config", str(tmp_path / "ceres.yaml"))

    try:
        matched = await engine.variables.where(command.read(Variable.Filter))
        assert [variable.name for variable in matched] == ["__enabled__", "x", "y"]
    finally:
        await engine.database.dispose()


async def test_a_value_filter_compares_against_the_parsed_value(tmp_path: Path) -> None:
    """A value reads as YAML, so a number compares as a number rather than as its text."""
    engine = await _build_project(tmp_path)
    Command = create_entity_select_command(Variable)

    try:
        # A null names the field like any other value, so it selects the variables
        # holding one rather than falling back to matching everything.
        for argument, expected in (
            ("5", ["x"]),
            ("true", ["__enabled__"]),
            ("6", []),
            ("null", ["y"]),
        ):
            command = _invoke(Command, "--value", argument)
            filter = command.read(Variable.Filter)
            assert [variable.name for variable in await engine.variables.where(filter)] == expected
            # The in-memory matcher and the compiled query agree on the same values.
            assert [
                variable.name
                for variable in await engine.variables.where()
                if filter.matches(variable)
            ] == expected
    finally:
        await engine.database.dispose()


async def test_the_internal_predicate_splits_the_two_naming_conventions(tmp_path: Path) -> None:
    """An internal variable is one whose name both opens and closes with two underscores."""
    engine = await _build_project(tmp_path)
    Command = create_entity_count_command(Variable)

    try:
        for argument, expected in (("--internal", 1), ("--no-internal", 2)):
            filter = _invoke(Command, argument).read(Variable.Filter)
            assert await engine.variables.where(filter).count() == expected
    finally:
        await engine.database.dispose()
