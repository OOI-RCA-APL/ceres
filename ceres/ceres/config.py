from __future__ import annotations

import itertools
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping, Sequence, overload

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

from .internal.utilities import (
    EmailStr,
    NameStr,
    decode_td,
    encode_td,
    frozendict,
    frozenlist,
)
from .path import (
    ComponentPath,
    ConnectionPath,
    DriverPath,
    LocalComponentPath,
    LocalConnectionPath,
    LocalDriverPath,
    LocalNotifierPath,
    NotifierPath,
    UnitPath,
    create_local_path,
)


class BaseConfigModel(BaseModel):
    class Config(BaseConfig):
        allow_mutation = False
        arbitrary_types_allowed = True
        json_encoders = {
            timedelta: encode_td,
        }


class ComponentReferencesConfig(BaseConfigModel):
    connections: frozendict[str, str] = frozendict()
    drivers: frozendict[str, str] = frozendict()
    notifiers: frozendict[str, str] = frozendict()

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


class ComponentConfig(BaseConfigModel):
    name: NameStr
    component: str | object
    parameters: frozendict[str, Any] = frozendict()
    references: ComponentReferencesConfig = ComponentReferencesConfig()


class ConnectionReconnectConfig(BaseConfigModel):
    interval: timedelta = timedelta(seconds=1)
    backoff: float | None = 2
    max_interval: timedelta | None = timedelta(seconds=60)

    @validator("interval", "max_interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return _validate_positive_timedelta(value)


class ConnectionConfig(ComponentConfig):
    reconnect: ConnectionReconnectConfig = ConnectionReconnectConfig()


class DriverConfig(ComponentConfig):
    pass


class ScheduleKind(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    AND = "and"
    OR = "or"


class BaseScheduleConfig(BaseConfigModel):
    kind: ScheduleKind


class CronScheduleConfig(BaseScheduleConfig):
    kind: Literal[ScheduleKind.CRON] = ScheduleKind.CRON
    crontab: str

    @validator("crontab")
    def _validate_crontab(cls, crontab: str) -> str:
        return _validate_crontab(crontab)


class IntervalScheduleConfig(BaseScheduleConfig):
    kind: Literal[ScheduleKind.INTERVAL] = ScheduleKind.INTERVAL
    interval: timedelta

    @validator("interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return _validate_positive_timedelta(value)


class AndScheduleConfig(BaseScheduleConfig):
    kind: Literal[ScheduleKind.AND] = ScheduleKind.AND
    schedules: frozenlist[ScheduleConfig]


class OrScheduleConfig(BaseScheduleConfig):
    kind: Literal[ScheduleKind.OR] = ScheduleKind.OR
    schedules: frozenlist[ScheduleConfig]


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
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return _validate_positive_timedelta(value)


class ServerConfig(BaseConfigModel):
    port: int
    enable: bool = True


class DatabaseKind(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DatabaseRetryConfig(BaseConfigModel):
    timeout: timedelta = timedelta(seconds=15)
    interval: timedelta = timedelta(seconds=3)

    @validator("timeout", "interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return _validate_positive_timedelta(value)


class BaseDatabaseConfig(BaseConfigModel):
    kind: DatabaseKind
    engine: frozendict[str, Any] | None = None
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


class UnitConfig(BaseConfigModel):
    name: NameStr
    connections: frozenlist[ConnectionConfig] = frozenlist()
    drivers: frozenlist[DriverConfig] = frozenlist()
    notifiers: frozenlist[NotifierConfig] = frozenlist()

    @validator("connections")
    def _validate_connections(
        cls,
        connections: Sequence[ConnectionConfig],
    ) -> Sequence[ConnectionConfig]:
        for name, group in itertools.groupby(connections, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate connection name '{name}'")

        return connections

    @validator("drivers")
    def _validate_drivers(
        cls,
        drivers: Sequence[DriverConfig],
    ) -> Sequence[DriverConfig]:
        for name, group in itertools.groupby(drivers, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate driver name '{name}'")

        return drivers

    @validator("notifiers")
    def _validate_notifiers(
        cls,
        notifiers: Sequence[NotifierConfig],
    ) -> Sequence[NotifierConfig]:
        for name, group in itertools.groupby(notifiers, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate notifier name '{name}'")

        return notifiers

    @root_validator
    def _validate_references(cls, fields: Mapping[str, Any]) -> Mapping[str, Any]:
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


class UserConfig(BaseConfigModel):
    username: NameStr
    email: EmailStr
    meta: frozendict[str, Any] = frozendict()


class Config(BaseConfigModel):
    server: ServerConfig
    database: DatabaseConfig
    users: frozenlist[UserConfig] = frozenlist()
    units: frozenlist[UnitConfig] = frozenlist()

    __path__: Path | None = PrivateAttr(default=None)
    __component_path_cache__: dict[ComponentPath, ComponentConfig] = PrivateAttr(default={})

    @property
    def path(self) -> Path | None:
        return self.__path__

    @validator("units")
    def _validate_units(cls, units: list[UnitConfig]) -> list[UnitConfig]:
        for name, group in itertools.groupby(units, lambda unit: unit.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate unit name '{name}'")

        return units

    def get_unit(self, path: str | UnitPath) -> UnitConfig | None:
        if isinstance(path, UnitPath):
            path = path.name

        return next(unit for unit in self.units if unit.name == path)

    @overload
    def get_component(self, path: ConnectionPath) -> ConnectionConfig | None:
        ...

    @overload
    def get_component(self, path: DriverPath) -> DriverConfig | None:
        ...

    @overload
    def get_component(self, path: NotifierPath) -> NotifierConfig | None:
        ...

    def get_component(self, path: ComponentPath) -> ComponentConfig | None:
        if path in self.__component_path_cache__:
            return self.__component_path_cache__[path]

        component: ComponentConfig | None = None

        if unit := self.get_unit(path.unit):
            match path:
                case ConnectionPath():
                    component = next(
                        (current for current in unit.connections if current.name == path.name), None
                    )
                case DriverPath():
                    component = next(
                        (current for current in unit.drivers if current.name == path.name), None
                    )
                case NotifierPath():
                    component = next(
                        (current for current in unit.notifiers if current.name == path.name), None
                    )

        if component:
            self.__component_path_cache__[path] = component

        return component


def _validate_positive_timedelta(value: Any) -> timedelta:
    if (decoded := decode_td(value)) <= timedelta():
        raise ValueError("must be greater than zero")

    return decoded


def _validate_crontab(value: str) -> str:
    try:
        CronTrigger.from_crontab(value)
    except Exception:
        raise ValueError("invalid crontab expression")

    return value
