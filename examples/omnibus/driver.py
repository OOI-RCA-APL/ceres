from datetime import timedelta
from re import compile
from typing import Literal

from ceres import (
    Bound,
    Component,
    Connection,
    Directory,
    Level,
    Message,
    ParseFailed,
    ParticleData,
    GroupedRegexParticle,
    SplitByLine,
    action,
    listener,
    query,
    routine,
    sieve,
    utc,
)
from ceres.concurrency import sleep
from ceres.data import DataObject, Number, PositiveTimeDelta
from ceres.event import ConnectedEvent, DisconnectedEvent, ParticleEvent


class NavigationData(ParticleData):
    latitude: Number
    longitude: Number
    depth: Number
    heading: Number
    speed: Number


class NavigationParticle(GroupedRegexParticle[NavigationData]):
    type: Literal["sub/navigation"] = "sub/navigation"

    regex = compile(
        rb"NAV\s+"
        rb"(?P<latitude>-?\d+\.\d+)\s+"
        rb"(?P<longitude>-?\d+\.\d+)\s+"
        rb"(?P<depth>-?\d+(?:\.\d+)?)\s+"
        rb"(?P<heading>\d+(?:\.\d+)?)\s+"
        rb"(?P<speed>\d+(?:\.\d+)?)"
    )


class EnvironmentData(ParticleData):
    temperature: Number
    salinity: Number
    pressure: Number
    dissolved_oxygen: Number


class EnvironmentParticle(GroupedRegexParticle[EnvironmentData]):
    type: Literal["sub/environment"] = "sub/environment"

    regex = compile(
        rb"(?P<temperature>-?\d+(?:\.\d+)?),"
        rb"(?P<salinity>\d+(?:\.\d+)?),"
        rb"(?P<pressure>\d+(?:\.\d+)?),"
        rb"(?P<dissolved_oxygen>\d+(?:\.\d+)?)"
    )


class DepthLimits(DataObject):
    warning: float = 400.0
    critical: float = 450.0


class TemperatureLimits(DataObject):
    low: float = 0.0
    high: float = 25.0


class SubmarineStatus(DataObject):
    navigation_connected: bool = False
    environment_connected: bool = False
    latest_depth: float | None = None
    latest_temperature: float | None = None
    latest_heading: float | None = None
    latest_speed: float | None = None


class OmnibusDriver(Component):
    navigation: Bound[Connection] | None = Connection.Field(
        splitter=SplitByLine(),
        suffix=b"\n",
        receive_timeout=10,
    )

    environment: Bound[Connection] | None = Connection.Field(
        splitter=SplitByLine(),
        receive_timeout=15,
    )

    output: Directory

    depth_limits: DepthLimits
    temperature_limits: TemperatureLimits

    health_check_interval: PositiveTimeDelta = timedelta(minutes=1)

    def __setup__(self) -> None:
        self._status = SubmarineStatus()

    @sieve(navigation)
    async def parse_navigation(self, message: Message) -> NavigationParticle | None:
        try:
            return NavigationParticle.from_message(message)
        except ParseFailed as exception:
            self.system.log.warning(exception)
            return None

    @sieve(environment)
    async def parse_environment(self, message: Message) -> EnvironmentParticle | None:
        try:
            return EnvironmentParticle.from_message(message)
        except ParseFailed as exception:
            self.system.log.warning(exception)
            return None

    @listener(reference="navigation")
    def on_navigation_connected(self, event: ConnectedEvent) -> None:
        self._status.navigation_connected = True
        self.system.log.info("Navigation link established.")

    @listener(reference="navigation")
    def on_navigation_disconnected(self, event: DisconnectedEvent) -> None:
        self._status.navigation_connected = False
        self.system.alerts.emit(
            Level.WARNING,
            "sub/navigation-lost",
            {"message": "Navigation data link lost."},
        )

    @listener(reference="environment")
    def on_environment_connected(self, event: ConnectedEvent) -> None:
        self._status.environment_connected = True
        self.system.log.info("Environment sensor link established.")

    @listener(reference="environment")
    def on_environment_disconnected(self, event: DisconnectedEvent) -> None:
        self._status.environment_connected = False
        self.system.alerts.emit(
            Level.WARNING,
            "sub/environment-lost",
            {"message": "Environment sensor link lost."},
        )

    @listener
    def on_particle(self, event: ParticleEvent) -> None:
        if isinstance(event.particle.data, NavigationData):
            navigation = event.particle.data
            self._status.latest_depth = float(navigation.depth)
            self._status.latest_heading = float(navigation.heading)
            self._status.latest_speed = float(navigation.speed)
            self._check_depth(float(navigation.depth))
            self._write_data_file(
                "navigation",
                f"{event.particle.timestamp.isoformat()},"
                f"{navigation.latitude},{navigation.longitude},"
                f"{navigation.depth},{navigation.heading},{navigation.speed}\n",
            )

        elif isinstance(event.particle.data, EnvironmentData):
            environment = event.particle.data
            self._status.latest_temperature = float(environment.temperature)
            self._check_temperature(float(environment.temperature))
            self._write_data_file(
                "environment",
                f"{event.particle.timestamp.isoformat()},"
                f"{environment.temperature},{environment.salinity},"
                f"{environment.pressure},{environment.dissolved_oxygen}\n",
            )

    @routine(restart="always", restart_delay=60)
    async def health_check(self) -> None:
        while True:
            await sleep(self.health_check_interval)

            if not self._status.navigation_connected:
                self.system.alerts.emit(
                    Level.ERROR,
                    "sub/health-check-failed",
                    {"reason": "Navigation link is down."},
                )

            if not self._status.environment_connected:
                self.system.alerts.emit(
                    Level.ERROR,
                    "sub/health-check-failed",
                    {"reason": "Environment sensor link is down."},
                )

            recent_count = await self.system.particles.where(
                timespan=self.health_check_interval,
            ).count()
            self.system.log.info(
                f"Health check: {recent_count} particles in the last "
                f"{int(self.health_check_interval.total_seconds())}s."
            )

    @query
    async def status(self) -> dict:
        return {
            "navigation_connected": self._status.navigation_connected,
            "environment_connected": self._status.environment_connected,
            "latest_depth": self._status.latest_depth,
            "latest_temperature": self._status.latest_temperature,
            "latest_heading": self._status.latest_heading,
            "latest_speed": self._status.latest_speed,
        }

    @query
    async def recent_navigation(self, limit: int = 10) -> list[dict]:
        particles = await self.system.particles.where(
            cls=NavigationData,
            order="timestamp:desc",
        ).limit(limit)
        return [
            {
                "timestamp": particle.timestamp.isoformat(),
                "latitude": particle.data.latitude,
                "longitude": particle.data.longitude,
                "depth": particle.data.depth,
                "heading": particle.data.heading,
                "speed": particle.data.speed,
            }
            for particle in particles
        ]

    @action
    async def navigate_to(self, latitude: float, longitude: float) -> dict:
        connection = self.system.connections.get("navigation")
        if connection is None:
            return {"status": "error", "reason": "Navigation link is not configured."}

        command = f"NAV_TO {latitude:.6f} {longitude:.6f}".encode()
        await connection.send(command)
        self.system.log.info(
            f"Navigation command sent: heading to ({latitude:.6f}, {longitude:.6f})."
        )
        return {"status": "ok", "latitude": latitude, "longitude": longitude}

    @action
    async def stop_navigation(self) -> dict:
        connection = self.system.connections.get("navigation")
        if connection is None:
            return {"status": "error", "reason": "Navigation link is not configured."}

        await connection.send(b"NAV_STOP")
        self.system.log.info("Navigation stop command sent.")
        return {"status": "ok"}

    @action
    async def clear_alerts(self, before_seconds: int = 3600) -> dict:
        cutoff = utc() - timedelta(seconds=before_seconds)
        count = await self.system.alerts.where(before=cutoff).count()
        await self.system.alerts.where(before=cutoff).delete()
        self.system.log.info(f"Cleared {count} alerts older than {before_seconds}s.")
        return {"cleared": count}

    def _check_depth(self, depth: float) -> None:
        if depth >= self.depth_limits.critical:
            self.system.alerts.emit(
                Level.ERROR,
                "sub/depth-critical",
                {"depth": depth, "limit": self.depth_limits.critical},
            )
        elif depth >= self.depth_limits.warning:
            self.system.alerts.emit(
                Level.WARNING,
                "sub/depth-warning",
                {"depth": depth, "limit": self.depth_limits.warning},
            )

    def _check_temperature(self, temperature: float) -> None:
        if temperature < self.temperature_limits.low:
            self.system.alerts.emit(
                Level.WARNING,
                "sub/temperature-low",
                {
                    "temperature": temperature,
                    "limit": self.temperature_limits.low,
                },
            )
        elif temperature > self.temperature_limits.high:
            self.system.alerts.emit(
                Level.WARNING,
                "sub/temperature-high",
                {
                    "temperature": temperature,
                    "limit": self.temperature_limits.high,
                },
            )

    def _write_data_file(self, category: str, line: str) -> None:
        path = utc().strftime(f"{category}/%Y/%m-%d.csv")
        with self.output.open(path, "a") as stream:
            stream.write(line)
