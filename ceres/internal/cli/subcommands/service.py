import sys
from pathlib import Path
from typing import Annotated

from ceres.config import ConfigCheckType
from ceres.internal.cli.plumbing import CLIArgument, CLIRouter
from ceres.internal.cli.service import LaunchDService, Service, SystemDService
from ceres.internal.cli.shared import Dummy, ProjectOption, write, write_table
from ceres.internal.project import Project

router = CLIRouter(
    name="service",
    help="Manage a user-level SystemD or LaunchD background service for this project.",
)


@router.command()
def generate(
    path: Annotated[
        Path | None,
        CLIArgument(
            Path | None,
            dir_okay=False,
            resolve_path=True,
            writable=True,
            help="File path to write to. Standard output is used if not specified.",
        ),
    ] = None,
    *,
    project: Annotated[Project, ProjectOption(checks=[])] = Dummy(),
) -> None:
    """
    Generate a service definition file for this project.
    """
    service = _get_service(project)
    defintition = service.generate()

    if path is None:
        sys.stdout.buffer.write(defintition)  # type: ignore
        sys.stdout.flush()
    else:
        path.write_bytes(defintition)


@router.command()
def start(
    project: Annotated[Project, ProjectOption(checks=ConfigCheckType.all())] = Dummy()
) -> None:
    """
    Start the background service, creating and/or updating the service file as needed.
    """
    service = _get_service(project)
    write("All checks passed.")
    write(f"Starting service {service.name!r} at {service.location!r}...")
    service.start()
    write("Service started successfully.")


@router.command()
def stop(project: Annotated[Project, ProjectOption(checks=[])] = Dummy()) -> None:
    """
    Stop the background service, deleting the service file afterwards.
    """
    service = _get_service(project)
    write(f"Stopping service {service.name!r} at {service.location}...")
    service.stop()
    write("Service stopped successfully.")


@router.command()
def status(project: Annotated[Project, ProjectOption(checks=[])] = Dummy()) -> None:
    """
    Show the status of the background service.
    """
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


def _get_service(project: Project) -> Service:
    if sys.platform == "linux":
        return SystemDService(project, silent=False)
    if sys.platform == "darwin":
        return LaunchDService(project, silent=False)

    raise NotImplementedError(f"unsupported platform: {sys.platform}")
