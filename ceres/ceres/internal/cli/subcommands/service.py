import rich
from rich.box import ROUNDED
from rich.style import Style

from ceres.config import Config
from ceres.internal.cli.service import get_service
from ceres.internal.cli.shared import AsyncTyper, ConfigOption
from ceres.internal.config import ConfigCheckKind

service = AsyncTyper(
    name="service",
    no_args_is_help=True,
    add_completion=False,
)


@service.command()
def start(config: Config = ConfigOption(checks=ConfigCheckKind.all())) -> None:
    service = get_service(config)
    rich.print(f"All checks passed. Starting service {service.name!r} at {service.location!r}...")
    service.start()
    rich.print("Service started successfully.")


@service.command()
def stop(config: Config = ConfigOption(checks=[])) -> None:
    service = get_service(config)
    rich.print(f"Stopping service {service.name!r} at {service.location}...")
    service.stop()
    rich.print("Service stopped successfully.")


@service.command()
def status(config: Config = ConfigOption(checks=[])) -> None:
    from rich.table import Table

    service = get_service(config)

    table = Table(
        title="Service",
        title_style=Style(bold=True),
        box=ROUNDED,
    )
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

    rich.print(table)
