from typing import Annotated

from ceres._internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres._internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_database,
)
from ceres.particle import Particle, ParticleCreate, ParticleFilter, ParticleUpdate

router = CLIRouter(
    name="particle",
    help="Manage particles.",
)


class CLIParticleFilter(ValidateEmptyAsNone, ParticleFilter):
    pass


@router.command()
async def get(
    *,
    filter: Annotated[CLIParticleFilter, CLIOptionGroup()],
    context: CLIContext,
) -> Particle | None:
    """
    Retrieve one particle.
    """
    async with use_database(context) as database:
        return await database.particles.get(filter)


@router.command()
async def get_all(
    *,
    filter: Annotated[CLIParticleFilter, CLIOptionGroup()],
    context: CLIContext,
) -> list[Particle]:
    """
    Retrieve multiple particles.
    """
    async with use_database(context) as database:
        return await database.particles.get_all(filter)


@router.command()
async def count(
    *,
    filter: Annotated[CLIParticleFilter, CLIOptionGroup()],
    context: CLIContext,
) -> int:
    """
    Count particles.
    """
    async with use_database(context) as database:
        return await database.particles.count(filter)


@router.command()
async def create(
    *,
    data: Annotated[ParticleCreate, CLIOptionGroup()],
    context: CLIContext,
) -> Particle:
    """
    Create a new particle.
    """
    async with use_database(context) as database:
        return await database.particles.create(data)


@router.command()
async def update(
    *,
    filter: Annotated[CLIParticleFilter, CLIOptionGroup()],
    assign: Assign[ParticleUpdate],
    context: CLIContext,
) -> Particle | None:
    """
    Update one particle. Return if found.
    """
    async with use_database(context) as database:
        return await database.particles.update(filter, assign)


@router.command()
async def update_all(
    *,
    filter: Annotated[CLIParticleFilter, CLIOptionGroup()],
    assign: Assign[ParticleUpdate],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Update multiple particles. Return the number updated.
    """
    async with use_database(context) as database:
        if confirm:
            count = await database.particles.count(filter)
            get_confirmation(f"Update {count} particles?", abort=True)

        return await database.particles.update_all(filter, assign)


@router.command()
async def delete(
    *,
    filter: Annotated[CLIParticleFilter, CLIOptionGroup()],
    context: CLIContext,
) -> Particle | None:
    """
    Delete one particle. Return if found.
    """
    async with use_database(context) as database:
        return await database.particles.delete(filter)


@router.command()
async def delete_all(
    *,
    filter: Annotated[CLIParticleFilter, CLIOptionGroup()],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Delete multiple particles. Return the number deleted.
    """
    async with use_database(context) as database:
        if confirm:
            count = await database.particles.count(filter)
            get_confirmation(f"Delete {count} particles?", abort=True)

        return await database.particles.delete_all(filter)
