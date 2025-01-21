from __future__ import annotations

import sys
from typing import override

from pydantic import FilePath, NewPath
from pydantic_settings import CliPositionalArg, CliSubCommand

from ceres._internal.cli.shared import CliCommand, CliCommandGroup, write, write_table
from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    from ceres._internal.cli.service import LaunchDService, Service, SystemDService
    from ceres._internal.project import LoadedProject


class GenerateCommand(CliCommand):
    """
    Generate a service definition file for this project.
    """

    path: CliPositionalArg[FilePath | NewPath | None] = None
    """File path to write to. Standard output is used if not specified."""

    @override
    async def __run__(self) -> None:
        project = await self.use_loaded_project()
        service = _get_service(project)
        definition = service.generate()

        if self.path is None:
            sys.stdout.buffer.write(definition)
            sys.stdout.flush()
        else:
            self.path.write_bytes(definition)


class StartCommand(CliCommand):
    """
    Start the background service, creating and/or updating the service file as needed.
    """

    @override
    async def __run__(self) -> None:
        project = await self.use_loaded_project()
        service = _get_service(project)
        write(f"Starting service {service.name!r} at {service.location!r}...")
        service.start()
        write("Service started successfully.")


class StopCommand(CliCommand):
    """
    Stop the background service, deleting the service file afterwards.
    """

    @override
    async def __run__(self) -> None:
        project = await self.use_loaded_project()
        service = _get_service(project)
        write(f"Stopping service {service.name!r} at {service.location}...")
        service.stop()
        write("Service stopped successfully.")


class StatusCommand(CliCommand):
    """
    Show the status of the background service.
    """

    @override
    async def __run__(self) -> None:
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
    if sys.platform == "linux":
        return SystemDService(project, silent=False)
    if sys.platform == "darwin":
        return LaunchDService(project, silent=False)

    raise NotImplementedError(f"unsupported platform: {sys.platform}")


class ServiceCommand(CliCommandGroup):
    """
    Manage a user-level SystemD or LaunchD background service for this project.
    """

    generate: CliSubCommand[GenerateCommand]
    start: CliSubCommand[StartCommand]
    stop: CliSubCommand[StopCommand]
    status: CliSubCommand[StatusCommand]
