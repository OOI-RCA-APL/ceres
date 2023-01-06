import asyncio
import traceback
from dataclasses import dataclass
from logging import Logger
from types import MappingProxyType
from typing import AsyncIterable, Mapping, final
from uuid import UUID

from .address import LocalComponentAddress, UnitAddress, caddr
from .component import CallableProcedureKind, SubscribableProcedureKind
from .config import ConcurrencyKind, Config, UnitConfig
from .data import jsonify
from .database import Database
from .directory import Directory
from .errors import (
    ProcedureComponentNotLoadedError,
    ProcedureDoesNotExistError,
    ProcedureError,
)
from .internal import logs
from .internal.component import ComponentHandle, ComponentHandleContext
from .internal.tasklet import Tasklet
from .internal.utilities import sleep_forever, strify
from .result import Fail, Ok, Result


@dataclass(kw_only=True, frozen=True)
class UnitContext:
    id: UUID
    address: UnitAddress
    root_config: Config
    unit_config: UnitConfig
    database: Database | None = None

    def __post_init__(self) -> None:
        assert self.root_config.get_unit(self.address)
        assert self.unit_config in self.root_config.units


@final
class Unit(Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self.__context = context
        self.__database = context.database or Database(self.__context.root_config.database)
        self.__directory = Directory(
            (
                context.root_config.path.parent
                / context.root_config.paths.data
                / "units"
                / self.address.name
            )
            if context.root_config.path is not None
            else None
        )
        self.__component_handles: dict[str, ComponentHandle] = {}

    @property
    def id(self) -> UUID:
        return self.__context.id

    @property
    def address(self) -> UnitAddress:
        return self.__context.address

    @property
    def config(self) -> UnitConfig:
        return self.__context.unit_config

    @property
    def database(self) -> Database:
        return self.__database

    @property
    def directory(self) -> Directory:
        return self.__directory

    @property
    def concurrency(self) -> ConcurrencyKind:
        return (
            self.__context.unit_config.concurrency or self.__context.root_config.runtime.concurrency
        )

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.__context.address))

    @property
    def components(self) -> Mapping[str, ComponentHandle]:
        return MappingProxyType(self.__component_handles)

    def get_component_handle(self, address: LocalComponentAddress) -> ComponentHandle | None:
        return self.__component_handles.get(address if isinstance(address, str) else address.name)

    async def call(
        self,
        address: LocalComponentAddress,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        if (component := self.get_component_handle(address)) is None:
            return Fail(ProcedureDoesNotExistError())
        if component.instance is None:
            return Fail(ProcedureComponentNotLoadedError())

        return await component.instance.call(kind, procedure, input)

    async def subscribe(
        self,
        address: LocalComponentAddress,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[AsyncIterable[object | None], ProcedureError]:
        if (component := self.get_component_handle(address)) is None:
            return Fail(ProcedureDoesNotExistError())
        if component.instance is None:
            return Fail(ProcedureComponentNotLoadedError())

        return await component.instance.subscribe(kind, procedure, input)

    async def __run__(self) -> None:
        await self.__load_components()

        for component in self.components.values():
            component.start(
                on_exception=self.__on_component_exception,
                on_completed=self.__on_component_completed,
            )

        await sleep_forever()

    async def __stop__(self) -> None:
        async def stop() -> None:
            try:
                for component in reversed(self.components.values()):
                    self.logger.info(f"Stopping component '{component.address}'...")
                    await component.stop()

            finally:
                if self.__context.database is None:
                    await self.__database.dispose()

        await asyncio.shield(asyncio.create_task(stop()))

    async def __load_components(self) -> None:
        for component_config in self.config.components:
            address = caddr(self.address.name, component_config.name)

            if component_config.name in self.__component_handles:
                continue

            id = await self.__database.entities.get_address_id(address)

            self.__component_handles[component_config.name] = ComponentHandle(
                ComponentHandleContext(
                    id=id,
                    address=address,
                    root_config=self.__context.root_config,
                    unit_config=self.config,
                    component_config=component_config,
                    unit=self,
                )
            )

        for component_handle in self.__component_handles.values():
            match await component_handle.load():
                case Ok():
                    self.logger.info(
                        f"Loaded '{component_handle.address}' as {strify(type(component_handle.instance))} with id '{component_handle.id}'."
                    )
                case Fail(error):
                    self.logger.error(
                        f"Failed to load component '{component_handle.address}'. Error: {jsonify(error, indent=2)}"
                    )

    def __on_component_exception(self, handle: ComponentHandle, exception: BaseException) -> None:
        self.logger.error(
            f"Exception occurred in component '{handle.address}': {traceback.format_exception(exception)}"
        )

    def __on_component_completed(self, handle: ComponentHandle) -> None:
        self.logger.info(f"Component '{handle.address}' stopped.")
