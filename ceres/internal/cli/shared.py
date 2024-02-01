import os
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Annotated, Any, Optional, Sequence

from typer import Option

from ceres.config import Config, ConfigCheckType
from ceres.data import jsonify
from ceres.internal.cli.exceptions import CLIDatabaseUnreachableException, CLIInvalidConfigException
from ceres.internal.project import Project
from ceres.internal.utilities import syncify
from ceres.result import Ok

chdir = os.chdir


def __disabled_chdir__(*args: Any, **kwargs: Any) -> None:
    warnings.warn("Changing directory is disabled while running Ceres.")


def disable_chdir() -> None:
    os.chdir = __disabled_chdir__


def get_config_path(config_path: Path | None = None) -> Path:
    if config_path is None:
        possibilities = [
            Path(name)
            for name in (
                "ceres.yaml",
                "ceres.yml",
                "ceres.json",
            )
        ]

        for possibility in possibilities:
            if possibility.is_file():
                config_path = possibility
                break
        else:
            raise CLIInvalidConfigException(
                f"Must be in a directory containing one of: {possibilities}"
            )

    config_path = config_path.absolute()
    chdir(config_path.parent)
    disable_chdir()
    sys.path.insert(0, str(config_path.parent))
    return config_path


async def get_config(
    config_path: Path | None,
    checks: Sequence[ConfigCheckType],
) -> Config:
    import rich

    match await Config.load(
        get_config_path(config_path),
        log=rich.print,
        checks=checks,
    ):
        case Ok(config):
            return config
        case fail:
            raise CLIInvalidConfigException(
                f"Failed to load configuration. {jsonify(fail, indent=2)}"
            )


async def get_project(
    config_path: Path | None,
    checks: Sequence[ConfigCheckType],
) -> Project:
    return Project(
        get_config_path(config_path),
        await get_config(config_path, checks),
    )


def ConfigPathOption() -> Any:
    return Option(
        ...,
        "--config",
        hidden=True,
        exists=True,
        resolve_path=True,
        dir_okay=False,
        callback=get_config_path,
    )


def ConfigOption(*, checks: Sequence[ConfigCheckType] = ()) -> Any:
    async def callback(
        config_path: Annotated[Optional[Path], ConfigPathOption()] = None,
    ) -> Config:
        return await get_config(config_path, checks)

    return Option(
        ...,
        "--config",
        hidden=True,
        exists=True,
        resolve_path=True,
        dir_okay=False,
        callback=syncify(callback),
    )


def ProjectOption(*, checks: Sequence[ConfigCheckType] = ()) -> Any:
    async def callback(
        config_path: Annotated[Optional[Path], ConfigPathOption()] = None,
    ) -> Project:
        return await get_project(config_path, checks)

    return Option(
        ...,
        "--config",
        hidden=True,
        exists=True,
        resolve_path=True,
        dir_okay=False,
        callback=syncify(callback),
    )


def Dummy() -> Any:
    return None


def get_yes_no(prompt: str, default: bool | None = None) -> bool:
    while True:
        if default is None:
            default_indicator = "y/n"
        elif default:
            default_indicator = "Y/n"
        else:
            default_indicator = "y/N"

        text = input(f"{prompt} ({default_indicator}): ").lower()
        if default is not None and text == "":
            return default
        if text in ("yes", "y"):
            return True
        if text in ("no", "n"):
            return False


def write(
    *args: object,
    sep: str = " ",
    end: str = "\n",
    file: IO[str] | None = None,
    flush: bool = False,
):
    import rich

    rich.print(
        *args,
        sep=sep,
        end=end,
        file=file,
        flush=flush,
    )


@contextmanager
def write_table(title: str | None = None):
    import rich.box
    from rich.table import Table

    table = Table(title=title, box=rich.box.ROUNDED, title_justify="left")
    yield table
    write(table)


def strbool(value: bool) -> str:
    return "Yes" if value else "No"


async def get_database(config: Config, *, initialized: bool = False):
    from ceres.database.database import Database

    database = Database(config.database)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    if initialized:
        if not await database.initialized():
            raise CLIDatabaseUnreachableException("Database appears uninitialized, exiting.")

    return database
