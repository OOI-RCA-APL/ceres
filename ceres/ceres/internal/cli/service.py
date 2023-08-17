import plistlib
import subprocess
import sys
import traceback
from abc import ABC, abstractmethod
from enum import Enum
from getpass import getuser
from pathlib import Path
from typing import Any, Sequence

from typing_extensions import override

from ceres.data import DataObject
from ceres.internal.cli.exceptions import CLIServiceConfigException
from ceres.internal.cli.shared import write
from ceres.internal.project import Project

if sys.platform == "darwin":
    import launchd
    import launchd.cmd
else:
    launchd: Any = None


class ServiceState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"


class ServiceStatus(DataObject):
    state: ServiceState
    location: str


class Service(ABC):
    def __init__(self, project: Project, silent: bool = True) -> None:
        if project.config.service is None:
            raise CLIServiceConfigException(
                "Service configuration is missing from the config file."
            )

        self.__project = project
        self.__service_config = project.config.service
        self.__silent = silent

    @property
    def project(self) -> Project:
        return self.__project

    @property
    def name(self) -> str:
        return self.__service_config.name

    @property
    def user(self) -> str:
        return self.__service_config.user or getuser()

    @property
    def stdout(self) -> Path | None:
        if self.__service_config.stdout is None or self.__service_config.stdout.is_absolute():
            return self.__service_config.stdout

        return self.__project.directory / self.__service_config.stdout

    @property
    def stderr(self) -> Path | None:
        if self.__service_config.stderr is None or self.__service_config.stderr.is_absolute():
            return self.__service_config.stderr

        return self.__project.directory / self.__service_config.stderr

    def _log(self, message: Any) -> None:
        if not self.__silent:
            write(message)

    @property
    @abstractmethod
    def state(self) -> ServiceState:
        ...

    @property
    @abstractmethod
    def location(self) -> str:
        ...

    @abstractmethod
    def create(self) -> None:
        ...

    @abstractmethod
    def delete(self) -> None:
        ...

    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...


class SystemDService(Service):
    @property
    @override
    def state(self) -> ServiceState:
        if self._execute(["is-active", "--user", self.label], log_output=False) != 0:
            return ServiceState.STOPPED

        return ServiceState.RUNNING

    @property
    def label(self) -> str:
        return self.name + ".service"

    @property
    @override
    def location(self) -> str:
        return str(self.path)

    @property
    def path(self) -> Path:
        return Path("~/.config/systemd/user").expanduser() / self.label

    @override
    def create(self) -> None:
        current = self.path.read_text() if self.path.exists() else None
        data = f"""\
[Unit]
Description="{self.label}"

[Service]
ExecStart={sys.executable} -m ceres run
WorkingDirectory={self.project.directory}
Restart=always

[Install]
WantedBy=default.target
"""

        if self.stdout:
            data += f"StandardOutput=file:{self.stdout}\n"
        if self.stderr:
            data += f"StandardError=file:{self.stderr}\n"

        if current != data:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(data)
            self._execute(["service-reload", "--user"])

        self._execute(["enable", "--user", self.label])

    @override
    def delete(self) -> None:
        self.path.unlink(missing_ok=True)

    def _execute(
        self,
        command: Sequence[Any],
        *,
        log_errors: bool = True,
        log_output: bool = False,
    ) -> int:
        result = subprocess.run(
            ["systemctl", *(str(segment) for segment in command)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if (log_errors and result.returncode != 0) or log_output:
            if result.stderr.strip():
                self._log(result.stderr)
        if log_output:
            if result.stdout.strip():
                self._log(result.stdout)

        return result.returncode

    @override
    def start(self) -> None:
        if self.state == ServiceState.RUNNING:
            return

        self.create()
        self._execute(["service-reload", "--user"])
        self._execute(["start", "--user", self.label])
        self._execute(["enable", "--user", self.label])

    @override
    def stop(self) -> None:
        if self.state == ServiceState.STOPPED:
            return

        try:
            self._execute(["stop", "--user", self.label])
            self._execute(["disable", "--user", self.label])
        except Exception:
            traceback.print_exc()

        self.delete()


class LaunchDService(Service):
    @property
    @override
    def state(self) -> ServiceState:
        if not self.path.exists():
            return ServiceState.STOPPED

        try:
            self._execute(["list", self.label], log_exceptions=False, log_output=False)
            return ServiceState.RUNNING
        except Exception:
            return ServiceState.STOPPED

    @property
    @override
    def location(self) -> str:
        return str(self.path)

    @property
    def label(self) -> str:
        return self.name

    @property
    def path(self) -> Path:
        return Path(launchd.plist.compute_filename(self.label, launchd.plist.USER))

    @property
    def target(self) -> str:
        return "user/501/" + self.label

    @override
    def create(self) -> None:
        current = plistlib.loads(self.path.read_text().encode()) if self.path.exists() else None
        data = {
            "Label": self.label,
            "UserName": self.user,
            "ProgramArguments": [sys.executable, "-m", "ceres", "run"],
            "WorkingDirectory": str(self.project.directory),
            "RunAtLoad": True,
        }

        if self.stdout:
            data["StandardOutPath"] = str(self.stdout)
        if self.stderr:
            data["StandardErrorPath"] = str(self.stderr)

        if current != data:
            launchd.plist.write(self.label, data)
            return

        self._execute(["enable", self.target])

    @override
    def delete(self) -> None:
        self.path.unlink(missing_ok=True)

    def _execute(
        self,
        command: Sequence[Any],
        *,
        log_exceptions: bool = False,
        log_output: bool = True,
    ) -> bytes | Exception | None:
        try:
            output = launchd.cmd.launchctl(*(str(segment) for segment in command))
            if log_output and output.strip():
                self._log(output)
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
        if self.state == ServiceState.RUNNING:
            return

        self.create()
        self._execute(["load", "-w", self.path])
        self._execute(["enable", self.target])

        try:
            self._execute(["start", self.target], log_output=False)
        except Exception:
            pass

    @override
    def stop(self) -> None:
        if self.state == ServiceState.STOPPED:
            return

        try:
            self._execute(["unload", "-w", self.path])
        except Exception:
            traceback.print_exc()

        self.delete()
