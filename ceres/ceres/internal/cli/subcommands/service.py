from ceres.config import Config, ConfigCheckKind
from ceres.internal.cli.service import get_service
from ceres.internal.cli.shared import AsyncTyper, ConfigOption, write, write_table

service = AsyncTyper(
    name="service",
    no_args_is_help=True,
    add_completion=False,
)


@service.command()
def start(config: Config = ConfigOption(checks=ConfigCheckKind.all())) -> None:
    service = get_service(config)
    write(f"All checks passed. Starting service {service.name!r} at {service.location!r}...")
    service.start()
    write("Service started successfully.")


@service.command()
def stop(config: Config = ConfigOption(checks=[])) -> None:
    service = get_service(config)
    write(f"Stopping service {service.name!r} at {service.location}...")
    service.stop()
    write("Service stopped successfully.")


@service.command()
def status(config: Config = ConfigOption(checks=[])) -> None:
    service = get_service(config)

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
