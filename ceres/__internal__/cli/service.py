import subprocess
import sys
import traceback
from abc import ABC, abstractmethod
from collections.abc import Sequence
from getpass import getuser
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

from ceres.__internal__.cli.shared import write
from ceres.data import DataModel, StrEnum

if TYPE_CHECKING:
    from ceres.__internal__.project import LoadedProject, Project
    from ceres.config import ServiceConfig


class ServiceState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"


class ServiceStatus(DataModel):
    state: ServiceState
    location: str


class Service(ABC):
    def __init__(self, project: LoadedProject, silent: bool = True) -> None:
        self._project = project
        self._silent = silent

    @property
    def project(self) -> Project:
        return self._project

    @property
    def config(self) -> ServiceConfig:
        return self._project.config.service

    @property
    def name(self) -> str:
        return self.config.name or "ceres-" + self._project.directory_hash

    @property
    def user(self) -> str:
        return self.config.user or getuser()

    @property
    def stdout(self) -> Path | None:
        if self.config.stdout is None or self.config.stdout.is_absolute():
            return self.config.stdout

        return self._project.directory / self.config.stdout

    @property
    def stderr(self) -> Path | None:
        if self.config.stderr is None or self.config.stderr.is_absolute():
            return self.config.stderr

        return self._project.directory / self.config.stderr

    def _log(self, message: Any) -> None:
        if not self._silent:
            write(message)

    @property
    @abstractmethod
    def state(self) -> ServiceState: ...

    @property
    @abstractmethod
    def location(self) -> str: ...

    @abstractmethod
    def generate(self) -> bytes: ...

    @abstractmethod
    def create(self) -> None: ...

    @abstractmethod
    def delete(self) -> None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


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
        current = self.path.read_bytes() if self.path.exists() else None
        data = self.generate()

        if current != data:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(data)
            self._execute(["daemon-reload", "--user"])

        self._execute(["enable", "--user", self.label])

    @override
    def delete(self) -> None:
        self.path.unlink(missing_ok=True)

    @override
    def generate(self) -> bytes:
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
            data += f"StandardOutput=append:{self.stdout}\n"
        if self.stderr:
            data += f"StandardError=append:{self.stderr}\n"

        return data.encode()

    @override
    def start(self) -> None:
        if self.state == ServiceState.RUNNING:
            return

        self.create()
        self._execute(["daemon-reload", "--user"])
        self._execute(["start", "--user", self.label])
        self._execute(["enable", "--user", self.label])
        self._enable_linger()

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
            text=True,
        )
        if (log_errors and result.returncode != 0) or log_output:
            if result.stderr.strip():
                self._log(result.stderr)
        if log_output:
            if result.stdout.strip():
                self._log(result.stdout)

        return result.returncode

    def _enable_linger(self) -> None:
        write(f"Enabling loginctl linger for user {self.user!r}...")
        result = subprocess.run(["loginctl", "enable-linger", self.user])
        if result.returncode != 0:
            write(
                f"WARNING: Failed to enable loginctl linger. "
                f"Execute 'loginctl enable-linger {self.user}' to persist the service after logout."
            )


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
        return Path("~/Library/LaunchAgents").expanduser() / f"{self.label}.plist"

    @property
    def target(self) -> str:
        return "user/501/" + self.label

    @override
    def generate(self) -> bytes:
        import plistlib

        return plistlib.dumps(self._generate_plist_data())

    @override
    def create(self) -> None:
        import plistlib

        try:
            current = plistlib.loads(self.path.read_text().encode()) if self.path.exists() else None
        except Exception:
            current = None

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
            self.path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
            self.path.write_bytes(plistlib.dumps(data))

        self._execute(["enable", self.target])

    @override
    def delete(self) -> None:
        self.path.unlink(missing_ok=True)

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

    def _execute(
        self,
        command: Sequence[Any],
        *,
        log_exceptions: bool = False,
        log_output: bool = True,
    ) -> bytes | Exception | None:
        try:
            command = ["launchctl", *[str(segment) for segment in command]]
            output = subprocess.check_output(command, stderr=subprocess.STDOUT)
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

    def _generate_plist_data(self) -> dict[str, Any]:
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

        return data
