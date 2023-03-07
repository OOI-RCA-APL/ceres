import asyncio
import traceback
from logging import Logger
from typing import TYPE_CHECKING, AsyncIterable, Mapping, Sequence, final
from weakref import ref

from pydantic import Field
from typing_extensions import override

from ceres.component import Component
from ceres.data import DataObject, Name
from ceres.directory import Directory
from ceres.environment import Environment
from ceres.errors import ProcedureComponentNotLoadedError
from ceres.events import Event
from ceres.exceptions import ProcedureException
from ceres.internal import logs
from ceres.internal.tasklet import Tasklet
from ceres.internal.utilities import sleep_forever
from ceres.stream import Stream, StreamView

if TYPE_CHECKING:
    from ceres.engine import Engine
else:
    Engine = "Engine"


class UnitPaths(DataObject):
    data: Directory = Field(default_factory=Directory)
    local: Directory = Field(default_factory=Directory)


@final
class Unit(Tasklet):
    def __init__(
        self,
        *,
        name: Name,
        paths: UnitPaths | None = None,
    ) -> None:
        self.__name = name
        self.__local_environment: Environment | None = None

        if paths is not None:
            self.__paths = paths
        else:
            self.__paths = UnitPaths()

        self.__engine: ref[Engine] | None = None
        self.__events: Stream[Event] = Stream()
        self.__components: dict[Name, Component] = {}

    @property
    def name(self) -> Name:
        return self.__name

    @property
    def environment(self) -> Environment:
        if self.engine is not None:
            return self.engine.environment

        if self.__local_environment is None:
            self.__local_environment = Environment()

        return self.__local_environment

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

    def bind(self, environment: Environment) -> None:
        self.__local_environment = environment

    def emit_event(self, event: Event) -> None:
        self.__events.put(event)
        if self.engine is not None:
            self.engine.emit_event(event)

    def attach_to_engine(self, engine: Engine) -> None:
        if self.engine is engine:
            return

        if self.engine is not None:
            self.detach_from_engine()

        engine.add_unit(self)
        self.__engine = ref(engine)

    def detach_from_engine(self) -> None:
        if self.engine is None:
            return

        self.engine.remove_unit(self)
        self.__engine = None

    def add_component(self, component: Component) -> None:
        current = self.get_component(component.name)
        if current is component:
            return
        if current is not None:
            self.remove_component(current)

        self.__components[component.name] = component
        component.attach_to_unit(self)

    def remove_component(self, component: Component) -> None:
        if self.get_component(component.name) is not component:
            return

        self.__components.pop(component.name, None)
        if component.unit is self:
            component.detach_from_unit()

    def get_component(self, name: Name) -> Component | None:
        return self.__components.get(name)

    async def call(
        self,
        component: Name,
        procedure: str,
        args: Mapping[Name, object] | None = None,
    ) -> object | None:
        instance = self.get_component(component)
        if instance is None:
            return ProcedureException(ProcedureComponentNotLoadedError())

        return await instance.call(procedure, args)

    def subscribe(
        self,
        component: Name,
        procedure: str,
        args: Mapping[Name, object] | None = None,
    ) -> AsyncIterable[object | None]:
        instance = self.get_component(component)
        if instance is None:
            raise ProcedureException(ProcedureComponentNotLoadedError())

        return instance.subscribe(procedure, args)

    @override
    async def __run__(self) -> None:
        for component in self.components:
            component.start(
                on_exception=self.__on_component_exception,
                on_completed=self.__on_component_completed,
            )

        await sleep_forever()

    @override
    async def __stop__(self) -> None:
        async def stop() -> None:
            try:
                for component in reversed(self.components):
                    self.logger.info(f"Stopping component '{component.address}'...")
                    await component.stop()

            finally:
                if self.__local_environment is not None:
                    await self.environment.database.dispose()

        await asyncio.shield(asyncio.create_task(stop()))

    def __on_component_exception(self, component: Component, exception: BaseException) -> None:
        self.logger.error(
            f"Exception occurred in component '{component.address}': "
            f"{traceback.format_exception(exception)}"
        )
        self.remove_component(component)

    def __on_component_completed(self, component: Component) -> None:
        self.logger.info(f"Component '{component.address}' stopped.")
        self.remove_component(component)
