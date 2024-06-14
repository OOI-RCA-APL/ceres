from typing import Annotated

from ceres._internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres._internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_database,
)
from ceres.variable import Variable, VariableFilter, VariableUpdate

router = CLIRouter(
    name="variable",
    help="Manage variables.",
)


class CLIVariableFilter(ValidateEmptyAsNone, VariableFilter):
    pass


@router.command()
async def get(
    *,
    filter: Annotated[CLIVariableFilter, CLIOptionGroup()],
    context: CLIContext,
) -> Variable | None:
    """
    Retrieve one variable.
    """
    async with use_database(context) as database:
        return await database.variables.get(filter)


@router.command()
async def get_all(
    *,
    filter: Annotated[CLIVariableFilter, CLIOptionGroup()],
    context: CLIContext,
) -> list[Variable]:
    """
    Retrieve multiple variables.
    """
    async with use_database(context) as database:
        return await database.variables.get_all(filter)


@router.command()
async def count(
    *,
    filter: Annotated[CLIVariableFilter, CLIOptionGroup()],
    context: CLIContext,
) -> int:
    """
    Count variables.
    """
    async with use_database(context) as database:
        return await database.variables.count(filter)


@router.command()
async def create(
    *,
    data: Annotated[Variable, CLIOptionGroup()],
    context: CLIContext,
) -> Variable:
    """
    Create a new variable.
    """
    async with use_database(context) as database:
        return await database.variables.create(data)


@router.command()
async def update(
    *,
    filter: Annotated[CLIVariableFilter, CLIOptionGroup()],
    assign: Assign[VariableUpdate],
    context: CLIContext,
) -> Variable | None:
    """
    Update one variable. Return if found.
    """
    async with use_database(context) as database:
        return await database.variables.update(filter, assign)


@router.command()
async def update_all(
    *,
    filter: Annotated[CLIVariableFilter, CLIOptionGroup()],
    assign: Assign[VariableUpdate],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Update multiple variables. Return the number updated.
    """
    async with use_database(context) as database:
        if confirm:
            count = await database.variables.count(filter)
            get_confirmation(f"Update {count} variables?", abort=True)

        return await database.variables.update_all(filter, assign)


@router.command()
async def delete(
    *,
    filter: Annotated[CLIVariableFilter, CLIOptionGroup()],
    context: CLIContext,
) -> Variable | None:
    """
    Delete one variable. Return if found.
    """
    async with use_database(context) as database:
        return await database.variables.delete(filter)


@router.command()
async def delete_all(
    *,
    filter: Annotated[CLIVariableFilter, CLIOptionGroup()],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Delete multiple variables. Return the number deleted.
    """
    async with use_database(context) as database:
        if confirm:
            count = await database.variables.count(filter)
            get_confirmation(f"Delete {count} variables?", abort=True)

        return await database.variables.delete_all(filter)
