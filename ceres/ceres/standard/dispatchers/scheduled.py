from dataclasses import field
from functools import partial
from typing import Sequence

from pydantic import Field
from typing_extensions import override

from ceres.roles.dispatcher import Dispatch, Dispatcher
from ceres.schedule import Schedule


class ScheduledDispatch(Dispatch):
    schedule: Schedule = Field(discriminator="kind")


class ScheduledDispatcher(Dispatcher):
    dispatches: Sequence[ScheduledDispatch] = field(default_factory=list)

    @override
    async def __run__(self) -> None:
        for dispatch in self.dispatches:
            self.add_job(
                partial(self.dispatch, dispatch),
                dispatch.schedule,
                name=f"dispatch-{dispatch.subject}",
            )

        await super().__run__()
