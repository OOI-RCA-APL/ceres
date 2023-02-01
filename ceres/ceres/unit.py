import asyncio
import traceback
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterable, Sequence, final
from weakref import ref

from .address import ComponentAddress
from .component import (
    CallableProcedureKind,
    Component,
    ComponentPaths,
    SubscribableProcedureKind,
)
from .config import UnitConfig
from .data import ImmutableDataObject, Name, jsonify
from .directory import Directory
from .environment import Environment
from .errors import ProcedureComponentNotLoadedError, ProcedureError
from .events import Event
from .internal import logs
from .internal.component import load_component
from .internal.tasklet import Tasklet
from .internal.utilities import sleep_forever, strify
from .result import Fail, Ok, Result
from .stream import Stream, StreamView

if TYPE_CHECKING:
    from .engine import Engine
else:
    Engine = "Engine"


class UnitPaths(ImmutableDataObject):
    local: Directory
    data: Directory


@final
class Unit(Tasklet):
    def __init__(
        self,
        *,
        config: UnitConfig,
        environment: Environment | None = None,
        paths: UnitPaths | None = None,
    ) -> None:
        self.__config = config

        if environment is not None:
            self.__environment = environment
            self.__has_exclusive_temporary_environment = False
        else:
            self.__environment = Environment()
            self.__has_exclusive_temporary_environment = True

        if paths is not None:
            self.__paths = paths
        else:
            self.__paths = UnitPaths(
                local=Directory(),
                data=Directory(),
            )

        self.__engine: ref[Engine] | None = None
        self.__events: Stream[Event] = Stream()
        self.__components: dict[Name, Component] = {}

    @property
    def name(self) -> Name:
        return self.__config.name

    @property
    def config(self) -> UnitConfig:
        return self.__config

    @property
    def environment(self) -> Environment:
        return self.__environment

    @property
    def engine(self) -> "Engine | None":
        if self.__engine is None:
            return None

        return self.__engine()

    @property
    def paths(self) -> UnitPaths:
        return self.__paths

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.name))

    @property
    def events(self) -> StreamView[Event]:
        return self.__events.view()

    @property
    def components(self) -> Sequence[Component]:
        return list(self.__components.values())

    def emit_event(self, event: Event) -> None:
        self.__events.put(event)
        if self.engine is not None:
            self.engine.emit_event(event)

    def attach_to_engine(self, engine: Engine) -> None:
        if engine.get_unit(self.name) is not self:
            raise ValueError("attached engine does not contain this unit")

        self.__engine = ref(engine)

    def detach_from_engine(self) -> None:
        self.__engine = None

    def __attach_component(self, component: Component) -> None:
        self.__components[component.name] = component
        component.attach_to_unit(self)

    def __detach_component(self, component: Component) -> None:
        self.__components.pop(component.name, None)
        if component.unit is self:
            component.detach_from_unit()

    def get_component(self, name: Name) -> Component | None:
        return self.__components.get(name)

    async def call(
        self,
        component: Name,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        instance = self.get_component(component)
        if instance is None:
            return Fail(ProcedureComponentNotLoadedError())

        return await instance.call(kind, procedure, input)

    async def subscribe(
        self,
        component: Name,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[AsyncIterable[object | None], ProcedureError]:
        instance = self.get_component(component)
        if instance is None:
            return Fail(ProcedureComponentNotLoadedError())

        return await instance.subscribe(kind, procedure, input)

    async def __run__(self) -> None:
        await self.__load_components()

        for component in self.components:
            component.start(
                on_exception=self.__on_component_exception,
                on_completed=self.__on_component_completed,
            )

        await sleep_forever()

    async def __stop__(self) -> None:
        async def stop() -> None:
            try:
                for component in reversed(self.components):
                    self.logger.info(f"Stopping component '{component.address}'...")
                    await component.stop()

            finally:
                if self.__has_exclusive_temporary_environment:
                    await self.environment.database.dispose()

        await asyncio.shield(asyncio.create_task(stop()))

    async def __load_components(self) -> None:
        for config in self.config.components:
            if self.get_component(config.name) is not None:
                continue

            address = ComponentAddress.create(self.name, config.name)
            id = await self.__environment.get_component_id(address)
            match load_component(
                config,
                id=id,
                address=address,
                environment=self.environment,
                paths=ComponentPaths(
                    unit=self.paths.local,
                    component=self.paths.local.subdir(Path("components") / self.config.name),
                    data=self.paths.data,
                ),
                siblings=self.__components,
            ):
                case Ok(component):
                    self.__attach_component(component)
                    self.logger.info(
                        f"Loaded '{component.address}' as {strify(type(component))} with id '{component.id}'."
                    )
                case Fail(error):
                    self.logger.error(
                        f"Failed to load component '{address}'. Error: {jsonify(error, indent=2)}"
                    )

    def __on_component_exception(self, component: Component, exception: BaseException) -> None:
        self.logger.error(
            f"Exception occurred in component '{component.address}': {traceback.format_exception(exception)}"
        )
        self.__detach_component(component)

    def __on_component_completed(self, component: Component) -> None:
        self.logger.info(f"Component '{component.address}' stopped.")
        self.__detach_component(component)
