from typing import Annotated

from fastapi import APIRouter, Depends

from ceres.address import Address
from ceres.errors import Failure, NotFoundError
from ceres.filter import ComponentFilter
from ceres.internal.app.shared import CurrentEngine, CurrentSocket
from ceres.status import Status

router = APIRouter(prefix="/statuses", tags=["statuses"])


@router.get("/{address}?")
async def get_status(engine: CurrentEngine, address: Address | None = None) -> Status:
    component = engine.get_component(address)
    if component is None:
        raise Failure(NotFoundError)

    return await component.get_status()


class GetStatusesQueryParameters(ComponentFilter):
    pass


@router.get("")
async def get_statuses(
    engine: CurrentEngine,
    filter: Annotated[GetStatusesQueryParameters, Depends()],
) -> list[Status]:
    return await engine.get_statuses(filter)


class StreamStatusesQueryParameters(GetStatusesQueryParameters):
    pass


@router.websocket("")
async def stream_statuses(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[StreamStatusesQueryParameters, Depends()],
) -> None:
    async for statuses in engine.stream_statuses(filter):
        await socket.send(statuses)
