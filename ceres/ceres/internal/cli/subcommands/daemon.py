import plistlib
import subprocess
import sys
import traceback
from abc import ABC, abstractmethod
from enum import Enum
from getpass import getuser
from pathlib import Path
from typing import Any, Sequence

import rich
from typing_extensions import override

from ceres.config import Config
from ceres.data import DataObject
from ceres.internal.cli.exceptions import CLIDaemonConfigException
from ceres.internal.cli.shared import AsyncTyper, ConfigOption

if sys.platform == "darwin":
    import launchd
    import launchd.cmd
else:
    launchd: Any = None

daemon = AsyncTyper(
    name="daemon",
    no_args_is_help=True,
    help="Manage the project daemon.",
)


class DaemonState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"


class DaemonStatus(DataObject):
    state: DaemonState
    location: str


class DaemonAdapter(ABC):
    def __init__(self, config: Config, silent: bool = True) -> None:
        if config.path is None:
            raise CLIDaemonConfigException("Path configuration is missing from the config file.")
        if config.daemon is None:
            raise CLIDaemonConfigException("Daemon configuration is missing from the config file.")

        self._root_config = config
        self._daemon_config = config.daemon
        self._silent = silent

    @property
    def name(self) -> str:
        return self._daemon_config.name

    @property
    def user(self) -> str:
        return self._daemon_config.user or getuser()

    @property
    def directory(self) -> Path:
        assert self._root_config.path is not None
        return self._root_config.path.parent

    @property
    def stdout(self) -> Path | None:
        if self._daemon_config.stdout is None or self._daemon_config.stdout.is_absolute():
            return self._daemon_config.stdout

        return self.directory / self._daemon_config.stdout

    @property
    def stderr(self) -> Path | None:
        if self._daemon_config.stderr is None or self._daemon_config.stderr.is_absolute():
            return self._daemon_config.stderr

        return self.directory / self._daemon_config.stderr

    def _log(self, message: Any) -> None:
        if not self._silent:
            rich.print(message)

    @property
    @abstractmethod
    def state(self) -> DaemonState:
        ...

    @property
    @abstractmethod
    def location(self) -> str:
        ...

    @abstractmethod
    def _write(self) -> None:
        ...

    @abstractmethod
    def _delete(self) -> None:
        ...

    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    def restart(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    def status(self) -> DaemonStatus:
        from rich.table import Table

        status = DaemonStatus(
            state=self.state,
            location=self.location,
        )

        if not self._silent:
            table = Table()
            table.add_column("State")
            table.add_column("Location")
            table.add_row(
                str(status.state.value).title(),
                status.location,
            )

            self._log(table)

        return status


class SystemDAdapter(DaemonAdapter):
    @property
    @override
    def state(self) -> DaemonState:
        if self.execute(["is-active", "--user", self.label], log_output=False) != 0:
            return DaemonState.STOPPED

        return DaemonState.RUNNING

    @property
    def label(self) -> str:
        return "ceres." + self.name + ".service"

    @property
    @override
    def location(self) -> str:
        return str(self.path)

    @property
    def path(self) -> Path:
        return Path("~/.config/systemd/user").expanduser() / self.label

    @override
    def _write(self) -> None:
        current = self.path.read_text() if self.path.exists() else None
        data = f"""\
[Unit]
Description="Ceres Daemon"

[Service]
ExecStart={sys.executable} -m ceres run
User={self.user}
Restart=always
KillUserProcesses=no

[Install]
WantedBy=multi-user.target
"""

        if self.stdout:
            data += f"StandardOutput=file:{self.stdout}\n"
        if self.stderr:
            data += f"StandardError=file:{self.stderr}\n"

        print(data)
        if current != data:
            print("diff")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(data)
            self.execute(["daemon-reload", "--user", self.label])

        self.execute(["enable", "--user", self.label])

    @override
    def _delete(self) -> None:
        self.path.unlink(missing_ok=True)

    def execute(
        self,
        command: Sequence[Any],
        *,
        log_output: bool = True,
    ) -> int:
        result = subprocess.run(
            ["systemctl", *(str(segment) for segment in command)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if log_output:
            if result.stderr.strip():
                rich.print(result.stderr)
            elif result.stdout.strip():
                rich.print(result.stdout)

        return result.returncode

    @override
    def start(self) -> None:
        if self.state == DaemonState.RUNNING:
            return

        self._write()
        self.execute(["daemon-reload", "--user"])
        self.execute(["start", "--user", self.label])
        self.execute(["enable", "--user", self.label])

    @override
    def restart(self) -> None:
        self.stop(delete=False)
        self.start()

    @override
    def stop(self, delete: bool = True) -> None:
        if self.state == DaemonState.STOPPED:
            return

        try:
            self.execute(["stop", "--user", self.label])
            self.execute(["disable", "--user", self.label])
        except Exception:
            traceback.print_exc()

        if delete:
            pass
            # self._delete()


class LaunchDAdapter(DaemonAdapter):
    @property
    @override
    def state(self) -> DaemonState:
        if not self.path.exists():
            return DaemonState.STOPPED

        try:
            self.execute(["list", self.label], log_exceptions=False, log_output=False)
            return DaemonState.RUNNING
        except Exception:
            return DaemonState.STOPPED

    @property
    @override
    def location(self) -> str:
        return str(self.path)

    @property
    def label(self) -> str:
        return "com.ceres." + self.name

    @property
    def path(self) -> Path:
        return Path(launchd.plist.compute_filename(self.label, launchd.plist.USER))

    @property
    def target(self) -> str:
        return "user/501/" + self.label

    @override
    def _write(self) -> None:
        current = plistlib.loads(self.path.read_text().encode()) if self.path.exists() else None
        data = {
            "Label": self.label,
            "UserName": self.user,
            "WorkingDirectory": str(self.directory),
            "ProgramArguments": [sys.executable, "-m", "ceres", "run"],
            "RunAtLoad": True,
        }

        if self.stdout:
            data["StandardOutPath"] = str(self.stdout)
        if self.stderr:
            data["StandardErrorPath"] = str(self.stderr)

        if current != data:
            launchd.plist.write(self.label, data)
            return

        self.execute(["enable", self.target])

    @override
    def _delete(self) -> None:
        self.path.unlink(missing_ok=True)

    def execute(
        self,
        command: Sequence[Any],
        *,
        log_exceptions: bool = False,
        log_output: bool = True,
    ) -> bytes | Exception | None:
        try:
            output = launchd.cmd.launchctl(*(str(segment) for segment in command))
            if log_output and output.strip():
                rich.print(output)
                return output
        except Exception as exception:
            if log_exceptions:
                traceback.print_exc()
            else:
                raise

            return exception

        return None

    @override
    def start(self) -> None:
        if self.state == DaemonState.RUNNING:
            return

        self._write()
        self.execute(["load", "-w", self.path])
        self.execute(["enable", self.target])

        try:
            self.execute(["start", self.target], log_output=False)
        except Exception:
            pass

    @override
    def restart(self) -> None:
        self.stop(delete=False)
        self.start()

    @override
    def stop(self, delete: bool = True) -> None:
        if self.state == DaemonState.STOPPED:
            return

        try:
            self.execute(["unload", "-w", self.path])
        except Exception:
            traceback.print_exc()

        if delete:
            self._delete()


def _get_adapter(config: Config) -> DaemonAdapter:
    if sys.platform == "linux":
        return SystemDAdapter(config, silent=False)
    if sys.platform == "darwin":
        return LaunchDAdapter(config, silent=False)

    raise NotImplementedError(f"unsupported platform: {sys.platform}")


@daemon.command()
def start(config: Config = ConfigOption(checks=[])) -> None:
    _get_adapter(config).start()


@daemon.command()
def restart(config: Config = ConfigOption(checks=[])) -> None:
    _get_adapter(config).restart()


@daemon.command()
def stop(config: Config = ConfigOption(checks=[])) -> None:
    _get_adapter(config).stop()


@daemon.command()
def status(config: Config = ConfigOption(checks=[])) -> None:
    _get_adapter(config).status()
