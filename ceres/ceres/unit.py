import asyncio
import traceback
from typing import final

from typing_extensions import override

from ceres.component import Component


@final
class Unit(Component):
    @override
    async def __run__(self) -> None:
        for component in self.children:
            component.start(
                on_exception=self.__on_component_exception,
                on_completed=self.__on_component_completed,
            )

        await super().__run__()

    @override
    async def __stop__(self) -> None:
        async def stop() -> None:
            for component in reversed(self.children):
                self.log.info(f"Stopping component '{component.address}'...")
                await component.stop()

        await asyncio.shield(asyncio.create_task(stop()))
        await super().__stop__()

    def __on_component_exception(self, component: Component, exception: BaseException) -> None:
        self.log.error(
            f"Exception occurred in component '{component.address}': "
            f"{traceback.format_exception(exception)}",
        )

    def __on_component_completed(self, component: Component) -> None:
        self.log.info(f"Component '{component.address}' stopped.")
