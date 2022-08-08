import click
from click import Path

from . import logs
from .app import App
from .internal import entrypoint
from .server import Server
from .supervisor import Supervisor

logger = logs.main()


@click.command()
@click.argument(
    "path",
    type=Path(
        exists=True,
        resolve_path=True,
        dir_okay=False,
    ),
)
@entrypoint
async def main(path: str) -> None:
    await App(path, Server, Supervisor).run()


if __name__ == "__main__":
    main()
