import sys
from typing import TYPE_CHECKING, override

from pydantic_settings import CliSubCommand

from ceres.__internal__.cli.shared import CLICommand, CLICommandFailed, CLICommandGroup

if TYPE_CHECKING:
    from ceres.config import ConfigMeta


class OpenCommand(CLICommand):
    """
    Open the project's web console in a browser.
    """

    @override
    async def __run__(self) -> None:
        """Resolve the console URL from the config and open it in the default browser."""
        from webbrowser import open

        config = await self.use_config_meta()
        url = _get_url(config)
        open(url)


class URLCommand(CLICommand):
    """
    Write the project's web console URL to stdout.
    """

    @override
    async def __run__(self) -> None:
        """Resolve the console URL from the config and write it to stdout."""
        config = await self.use_config_meta()
        url = _get_url(config)
        self.write(url, sys.stdout)


class ConsoleCommand(CLICommandGroup):
    """
    Commands for interacting with a project's web console.
    """

    open: CliSubCommand[OpenCommand]
    url: CliSubCommand[URLCommand]


def _get_url(config: ConfigMeta) -> str:
    """Build the web console URL from the project's server configuration.

    Args:
        config: The loaded configuration metadata containing server settings.

    Returns:
        The fully-qualified console URL string.

    Raises:
        CLICommandFailed: If the server or port is not configured.
    """
    if config.server is None or config.server.port is None:
        raise CLICommandFailed(
            "Server is not configured. "
            "Add `server` settings to `ceres.yaml` with a defined `port` number."
        )

    host = config.server.host
    port = config.server.port

    if host == "0.0.0.0":
        host = "localhost"

    scheme = "http" if config.server.ssl is None else "https"

    return f"{scheme}://{host}:{port}"
