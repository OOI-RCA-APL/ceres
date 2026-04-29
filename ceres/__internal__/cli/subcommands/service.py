import sys
from typing import TYPE_CHECKING, override

from pydantic import FilePath, NewPath
from pydantic_settings import CliPositionalArg, CliSubCommand

from ceres.__internal__.cli.shared import CLICommand, CLICommandGroup, write_table
from ceres.__internal__.utilities.platforms import LINUX, MACOS

if TYPE_CHECKING:
    from ceres.__internal__.cli.service import Service
    from ceres.__internal__.project import LoadedProject


class GenerateCommand(CLICommand):
    """
    Generate a service definition file for this project.
    """

    path: CliPositionalArg[FilePath | NewPath | None] = None
    """File path to write to. Standard output is used if not specified."""

    @override
    async def __run__(self) -> None:
        """Generate the service definition and write it to a file or stdout."""
        project = await self.use_loaded_project()
        service = _get_service(project)
        definition = service.generate()

        if self.path is None:
            sys.stdout.buffer.write(definition)
            sys.stdout.flush()
        else:
            self.path.write_bytes(definition)


class StartCommand(CLICommand):
    """
    Start the background service, creating and/or updating the service file as needed.
    """

    @override
    async def __run__(self) -> None:
        """Create or update the service definition, then start the service."""
        project = await self.use_loaded_project()
        service = _get_service(project)
        self.write(f"Starting service {service.name!r} at {service.location!r}...")
        service.start()
        self.write("Service started successfully.")


class StopCommand(CLICommand):
    """
    Stop the background service, deleting the service file afterwards.
    """

    @override
    async def __run__(self) -> None:
        """Stop the running service and delete its definition file."""
        project = await self.use_loaded_project()
        service = _get_service(project)
        self.write(f"Stopping service {service.name!r} at {service.location!r}...")
        service.stop()
        self.write("Service stopped successfully.")


class StatusCommand(CLICommand):
    """
    Show the status of the background service.
    """

    @override
    async def __run__(self) -> None:
        """Display the service name, user, state, and location in a table."""
        project = await self.use_loaded_project()
        service = _get_service(project)

        with write_table() as table:
            table.add_column("Name")
            table.add_column("User")
            table.add_column("State")
            table.add_column("Location")
            table.add_row(
                service.name,
                service.user,
                service.state.value.title(),
                service.location,
            )


def _get_service(project: LoadedProject) -> Service:
    """Return the platform-appropriate service manager for the given project.

    Args:
        project: The loaded project to manage as a service.

    Returns:
        A `SystemDService` on Linux or a `LaunchDService` on macOS.

    Raises:
        NotImplementedError: If the current platform is not Linux or macOS.
    """
    if LINUX:
        from ceres.__internal__.cli.service import SystemDService

        return SystemDService(project, silent=False)
    if MACOS:
        from ceres.__internal__.cli.service import LaunchDService

        return LaunchDService(project, silent=False)

    raise NotImplementedError(f"unsupported platform: {sys.platform}")


class ServiceCommand(CLICommandGroup):
    """
    Manage a user-level SystemD or LaunchD background service for this project.
    """

    generate: CliSubCommand[GenerateCommand]
    start: CliSubCommand[StartCommand]
    stop: CliSubCommand[StopCommand]
    status: CliSubCommand[StatusCommand]
