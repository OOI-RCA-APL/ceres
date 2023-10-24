from dataclasses import field
from typing import Sequence

from pydantic import Field

from ceres.component import routine
from ceres.roles.dispatcher import Dispatch, Dispatcher
from ceres.schedule import Schedule


class ScheduledDispatch(Dispatch):
    schedule: Schedule = Field(discriminator="type")


class ScheduledDispatcher(Dispatcher):
    dispatches: Sequence[ScheduledDispatch] = field(default_factory=list)

    @routine
    async def routine__setup_dispatch_jobs(self) -> None:
        for dispatch in self.dispatches:
            self.add_job(
                f"dispatch-{dispatch.subject}",
                dispatch.schedule,
                self.dispatch,
                arguments={"dispatch": dispatch},
            )
