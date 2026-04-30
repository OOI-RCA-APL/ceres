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
    """Possible states of a managed background service."""

    RUNNING = "running"
    STOPPED = "stopped"


class ServiceStatus(DataModel):
    """Data model representing the current status of a managed background service."""

    state: ServiceState
    """The current running state of the service."""

    location: str
    """The filesystem path of the service definition file."""


class Service(ABC):
    """Abstract base class for platform-specific background service managers."""

    def __init__(self, project: LoadedProject, silent: bool = True) -> None:
        """Initialize the service manager.

        Args:
            project: The loaded project this service manages.
            silent: If True, suppress log output from service operations.
        """
        self._project = project
        self._silent = silent

    @property
    def project(self) -> Project:
        """Return the project associated with this service."""
        return self._project

    @property
    def config(self) -> ServiceConfig:
        """Return the service configuration from the project config."""
        return self._project.config.service

    @property
    def name(self) -> str:
        """Return the service name, falling back to a hash-based name if not configured."""
        return self.config.name or "ceres-" + self._project.directory_hash

    @property
    def user(self) -> str:
        """Return the user the service runs as, defaulting to the current OS user."""
        return self.config.user or getuser()

    @property
    def stdout(self) -> Path | None:
        """Return the absolute path for stdout redirection, or None if not configured."""
        if self.config.stdout is None or self.config.stdout.is_absolute():
            return self.config.stdout

        return self._project.directory / self.config.stdout

    @property
    def stderr(self) -> Path | None:
        """Return the absolute path for stderr redirection, or None if not configured."""
        if self.config.stderr is None or self.config.stderr.is_absolute():
            return self.config.stderr

        return self._project.directory / self.config.stderr

    def _log(self, message: Any) -> None:
        """Write a message to the CLI output unless silent mode is active."""
        if not self._silent:
            write(message)

    @property
    @abstractmethod
    def state(self) -> ServiceState:
        """Return the current running state of the service."""
        ...

    @property
    @abstractmethod
    def location(self) -> str:
        """Return the filesystem path of the service definition file."""
        ...

    @abstractmethod
    def generate(self) -> bytes:
        """Generate the service definition file contents as bytes."""
        ...

    @abstractmethod
    def create(self) -> None:
        """Create or update the service definition file and register the service."""
        ...

    @abstractmethod
    def delete(self) -> None:
        """Remove the service definition file from disk."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Start the background service, creating the definition file if needed."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop the background service and remove its definition file."""
        ...


class SystemDService(Service):
    """Service manager for Linux systems using systemd user units."""

    @property
    @override
    def state(self) -> ServiceState:
        if self._execute(["is-active", "--user", self.label], log_output=False) != 0:
            return ServiceState.STOPPED

        return ServiceState.RUNNING

    @property
    def label(self) -> str:
        """Return the systemd unit name, including the `.service` suffix."""
        return self.name + ".service"

    @property
    @override
    def location(self) -> str:
        return str(self.path)

    @property
    def path(self) -> Path:
        """Return the path to the systemd unit file under `~/.config/systemd/user/`."""
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
        """Run a `systemctl` command and return its exit code.

        Args:
            command: Arguments to pass to `systemctl`.
            log_errors: If True, log stderr when the command fails.
            log_output: If True, log both stdout and stderr regardless of exit code.

        Returns:
            The process exit code.
        """
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
        """Enable `loginctl linger` so the user service persists after logout."""
        write(f"Enabling loginctl linger for user {self.user!r}...")
        result = subprocess.run(["loginctl", "enable-linger", self.user])
        if result.returncode != 0:
            write(
                f"WARNING: Failed to enable loginctl linger. "
                f"Execute 'loginctl enable-linger {self.user}' to persist the service after logout."
            )


class LaunchDService(Service):
    """Service manager for macOS systems using launchd user agents."""

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
        """Return the launchd job label for this service."""
        return self.name

    @property
    def path(self) -> Path:
        """Return the path to the plist file under `~/Library/LaunchAgents/`."""
        return Path("~/Library/LaunchAgents").expanduser() / f"{self.label}.plist"

    @property
    def target(self) -> str:
        """Return the launchd target specifier for this user-level service."""
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
        """Run a `launchctl` command and return its output or any raised exception.

        Args:
            command: Arguments to pass to `launchctl`.
            log_exceptions: If True, print tracebacks for caught exceptions.
            log_output: If True, log command output when present.

        Returns:
            The raw output bytes on success, the caught exception on failure, or None if there
            was no output.
        """
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
        """Build and return the plist dictionary for the launchd agent definition."""
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
