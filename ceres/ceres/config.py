from __future__ import annotations

import itertools
from abc import ABC
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from apscheduler.triggers.cron import CronTrigger
from pydantic import (
    BaseConfig,
    BaseModel,
    Field,
    PrivateAttr,
    SecretStr,
    root_validator,
    validator,
)

from .internal.utilities import EmailStr, NameStr, decode_td, encode_td
from .path import (
    LocalComponentPath,
    LocalConnectionPath,
    LocalDriverPath,
    LocalNotifierPath,
    create_local_path,
)


class ComponentReferencesConfig(BaseModel):
    connections: dict[str, str] = {}
    drivers: dict[str, str] = {}
    notifiers: dict[str, str] = {}

    def has(self, path: LocalComponentPath) -> bool:
        return self.remap(path) is not None

    def remap(self, path: LocalComponentPath) -> LocalComponentPath | None:
        match path:
            case LocalConnectionPath():
                name = self.connections.get(path.name)
            case LocalDriverPath():
                name = self.drivers.get(path.name)
            case LocalNotifierPath():
                name = self.notifiers.get(path.name)

        if name is None:
            return None

        return create_local_path(path.kind, name)


class ComponentConfig(BaseModel, ABC):
    class Config(BaseConfig):
        arbitrary_types_allowed = True

    name: NameStr
    component: str | object
    parameters: dict[str, Any] = {}
    references: ComponentReferencesConfig = ComponentReferencesConfig()


class ConnectionReconnectConfig(BaseModel):
    interval: timedelta = timedelta(seconds=1)
    backoff: float | None = 2
    max_interval: timedelta | None = timedelta(seconds=60)

    @validator("interval", "max_interval", pre=True)
    def _check_timedeltas(cls, value: Any) -> timedelta:
        if (parsed := decode_td(value)) <= timedelta():
            raise ValueError("must be greater than zero")

        return parsed


class ConnectionConfig(ComponentConfig):
    reconnect: ConnectionReconnectConfig = ConnectionReconnectConfig()


class DriverConfig(ComponentConfig):
    pass


class ScheduleKind(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    AND = "and"
    OR = "or"


class BaseScheduleConfig(BaseModel):
    kind: ScheduleKind


class CronScheduleConfig(BaseScheduleConfig):
    kind: Literal[ScheduleKind.CRON] = ScheduleKind.CRON
    crontab: str

    @validator("crontab")
    def _validate_crontab(cls, crontab: str) -> str:
        try:
            CronTrigger.from_crontab(crontab)
        except Exception:
            raise ValueError("invalid crontab expression")

        return crontab


class IntervalScheduleConfig(BaseScheduleConfig):
    kind: Literal[ScheduleKind.INTERVAL] = ScheduleKind.INTERVAL
    interval: timedelta

    @validator("interval", pre=True)
    def _check_timedeltas(cls, value: Any) -> timedelta:
        if (parsed := decode_td(value)) <= timedelta():
            raise ValueError("must be greater than zero")

        return parsed


class AndScheduleConfig(BaseScheduleConfig):
    kind: Literal[ScheduleKind.AND] = ScheduleKind.AND
    schedules: list[ScheduleConfig]


class OrScheduleConfig(BaseScheduleConfig):
    kind: Literal[ScheduleKind.OR] = ScheduleKind.OR
    schedules: list[ScheduleConfig]


ScheduleConfig = Annotated[
    CronScheduleConfig | IntervalScheduleConfig | AndScheduleConfig | OrScheduleConfig,
    Field(discriminator="kind"),
]

AndScheduleConfig.update_forward_refs()
OrScheduleConfig.update_forward_refs()


class NotifierConfig(ComponentConfig):
    schedule: ScheduleConfig | None = None
    lookback: timedelta

    @validator("lookback", pre=True)
    def _check_timedeltas(cls, value: Any) -> timedelta:
        if (parsed := decode_td(value)) <= timedelta():
            raise ValueError("must be greater than zero")

        return parsed


class ServerConfig(BaseModel):
    port: int
    enable: bool = True


class DatabaseKind(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DatabaseRetryConfig(BaseModel):
    timeout: timedelta = timedelta(seconds=15)
    interval: timedelta = timedelta(seconds=3)

    @validator("timeout", "interval", pre=True)
    def _check_timedeltas(cls, value: Any) -> timedelta:
        if (parsed := decode_td(value)) <= timedelta():
            raise ValueError("must be greater than zero")

        return parsed


class BaseDatabaseConfig(BaseModel):
    # kind: DatabaseKind
    engine: dict[str, Any] | None = None
    retry: DatabaseRetryConfig = DatabaseRetryConfig()


class SQLiteDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.SQLITE] = DatabaseKind.SQLITE
    path: Path


class PostgresDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.POSTGRES] = DatabaseKind.POSTGRES
    host: str
    port: int
    database: str
    user: str
    password: SecretStr


DatabaseConfig = Annotated[
    SQLiteDatabaseConfig | PostgresDatabaseConfig,
    Field(discriminator="kind"),
]


class UnitConfig(BaseModel):
    name: NameStr
    connections: list[ConnectionConfig] = []
    drivers: list[DriverConfig] = []
    notifiers: list[NotifierConfig] = []

    @validator("connections")
    def _check_connections(cls, connections: list[ConnectionConfig]) -> list[ConnectionConfig]:
        for name, group in itertools.groupby(connections, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate connection name '{name}'")

        return connections

    @validator("drivers")
    def _check_drivers(cls, connections: list[DriverConfig]) -> list[DriverConfig]:
        for name, group in itertools.groupby(connections, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate driver name '{name}'")

        return connections

    @root_validator
    def _check_references(cls, fields: dict[str, Any]) -> dict[str, Any]:
        name: str = fields["name"]
        connections: dict[str, ConnectionConfig] = {
            current.name: current for current in fields.get("connections", [])
        }
        drivers: dict[str, DriverConfig] = {
            current.name: current for current in fields.get("drivers", [])
        }
        components: list[ComponentConfig] = [*connections.values(), *drivers.values()]

        for component in components:
            for name in component.references.connections.values():
                if name not in connections:
                    raise ValueError(
                        f"invalid reference, connection '{name}' does not exist in unit '{name}'"
                    )

            for name in component.references.drivers.values():
                if name not in connections:
                    raise ValueError(
                        f"invalid reference, driver '{name}' does not exist in unit '{name}'"
                    )

        return fields


class UserConfig(BaseModel):
    username: NameStr
    email: EmailStr
    meta: dict[str, Any] = {}


class Config(BaseModel):
    class Config(BaseConfig):
        json_encoders = {
            timedelta: encode_td,
        }

    server: ServerConfig
    database: DatabaseConfig
    users: list[UserConfig] = []
    units: list[UnitConfig] = []

    __path__: Path | None = PrivateAttr(default=None)

    @property
    def path(self) -> Path | None:
        return self.__path__

    @validator("units")
    def _check_units(cls, units: list[UnitConfig]) -> list[UnitConfig]:
        for name, group in itertools.groupby(units, lambda unit: unit.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate unit name '{name}'")

        return units
