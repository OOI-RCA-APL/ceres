import sys

from ceres.config import ConfigCheckType
from ceres.internal.cli.service import LaunchDService, Service, SystemDService
from ceres.internal.cli.shared import AsyncTyper, ProjectOption, write, write_table
from ceres.internal.project import Project

service = AsyncTyper(
    name="service",
    no_args_is_help=True,
    add_completion=False,
)


@service.command()
def generate(project: Project = ProjectOption(checks=[])) -> None:
    service = _get_service(project)
    sys.stdout.buffer.write(service.generate())  # type: ignore
    sys.stdout.flush()


@service.command()
def start(project: Project = ProjectOption(checks=ConfigCheckType.all())) -> None:
    service = _get_service(project)
    write(f"All checks passed. Starting service {service.name!r} at {service.location!r}...")
    service.start()
    write("Service started and enabled successfully.")


@service.command()
def stop(project: Project = ProjectOption(checks=[])) -> None:
    service = _get_service(project)
    write(f"Stopping service {service.name!r} at {service.location}...")
    service.stop()
    write("Service stopped and disabled successfully.")


@service.command()
def status(project: Project = ProjectOption(checks=[])) -> None:
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
