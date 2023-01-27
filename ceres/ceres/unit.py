import asyncio
import traceback
from dataclasses import dataclass
from logging import Logger
from types import MappingProxyType
from typing import AsyncIterable, Mapping, Sequence, final

from .address import ComponentAddress
from .component import CallableProcedureKind, SubscribableProcedureKind
from .config import Config, UnitConfig
from .data import ImmutableDataObject, jsonify
from .database import Database
from .directory import Directory
from .errors import (
    ProcedureComponentNotLoadedError,
    ProcedureDoesNotExistError,
    ProcedureError,
)
from .events import Event
from .internal import logs
from .internal.component import ComponentHandle, ComponentHandleContext
from .internal.tasklet import Tasklet
from .internal.utilities import sleep_forever, strify
from .result import Fail, Ok, Result
from .stream import Stream, StreamView
from .types import Name


class UnitPaths(ImmutableDataObject):
    local: Directory
    data: Directory


@dataclass(kw_only=True, frozen=True)
class UnitContext:
    name: Name
    root_config: Config
    unit_config: UnitConfig
    database: Database
    forward: Sequence[Stream[Event]]

    def __post_init__(self) -> None:
        assert self.root_config.get_unit(self.name)
        assert self.unit_config in self.root_config.units


@final
class Unit(Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self.__context = context
        self.__database = context.database
        self.__events: Stream[Event] = Stream()

        local_path = Directory(
            (context.root_config.path.parent / context.root_config.paths.local / self.name)
            if context.root_config.path is not None
            else None
        )
        data_path = Directory(
            (context.root_config.path.parent / context.root_config.paths.data / self.name)
            if context.root_config.path is not None
            else None
        )
        self.__paths = UnitPaths(
            local=local_path,
            data=data_path,
        )

        self.__component_handles: dict[Name, ComponentHandle] = {}

    @property
    def name(self) -> Name:
        return self.__context.name

    @property
    def root_config(self) -> Config:
        return self.__context.root_config

    @property
    def config(self) -> UnitConfig:
        return self.__context.unit_config

    @property
    def database(self) -> Database:
        return self.__database

    @property
    def paths(self) -> UnitPaths:
        return self.__paths

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.__context.name))

    @property
    def components(self) -> Mapping[Name, ComponentHandle]:
        return MappingProxyType(self.__component_handles)

    @property
    def events(self) -> StreamView[Event]:
        return self.__events.view()

    def get_component_handle(self, name: Name) -> ComponentHandle | None:
        return self.__component_handles.get(name)

    async def call(
        self,
        component: Name,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        if (handle := self.get_component_handle(component)) is None:
            return Fail(ProcedureDoesNotExistError())
        if handle.instance is None:
            return Fail(ProcedureComponentNotLoadedError())

        return await handle.instance.call(kind, procedure, input)

    async def subscribe(
        self,
        component: Name,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[AsyncIterable[object | None], ProcedureError]:
        if (handle := self.get_component_handle(component)) is None:
            return Fail(ProcedureDoesNotExistError())
        if handle.instance is None:
            return Fail(ProcedureComponentNotLoadedError())

        return await handle.instance.subscribe(kind, procedure, input)

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
            address = ComponentAddress.create(self.name, component_config.name)

            if component_config.name in self.__component_handles:
                continue

            id = await self.__database.entities.get_component_id(address)

            self.__component_handles[component_config.name] = ComponentHandle(
                ComponentHandleContext(
                    id=id,
                    address=address,
                    root_config=self.__context.root_config,
                    unit_config=self.config,
                    component_config=component_config,
                    unit=self,
                    forward=[*self.__context.forward, self.__events],
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
