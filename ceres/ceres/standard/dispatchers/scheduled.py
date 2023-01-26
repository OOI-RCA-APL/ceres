from functools import partial
from typing import Sequence

from pydantic import Field

from ...dispatcher import Dispatch, Dispatcher
from ...schedule import Schedule


class ScheduledDispatch(Dispatch):
    schedule: Schedule = Field(discriminator="kind")


class ScheduledDispatcher(Dispatcher):
    class Parameters(Dispatcher.Parameters):
        dispatches: Sequence[ScheduledDispatch] = Field(default_factory=list)

    parameters: Parameters

    async def __run__(self) -> None:
        for dispatch in self.parameters.dispatches:
            self.add_job(
                partial(self.dispatch, dispatch),
                dispatch.schedule,
                name=f"dispatch-{dispatch.subject}",
            )

        await super().__run__()
