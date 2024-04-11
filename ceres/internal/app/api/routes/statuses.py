from fastapi import APIRouter

from ceres.address import Address
from ceres.errors import Failure, NotFoundError
from ceres.filter import SystemFilter
from ceres.internal.app.shared import CurrentEngine, CurrentSocket, QueryGroup
from ceres.status import Status

router = APIRouter(prefix="/statuses", tags=["statuses"])


@router.get("/{address}?")
async def get_status(engine: CurrentEngine, address: Address | None = None) -> Status:
    component = engine.get_node(address)
    if component is None:
        raise Failure(NotFoundError)

    return await component.get_status()


class GetStatusesQueryParameters(SystemFilter):
    pass


@router.get("")
async def get_statuses(
    engine: CurrentEngine,
    filter: QueryGroup[GetStatusesQueryParameters],
) -> list[Status]:
    return await engine.get_statuses(filter)


class StreamStatusesQueryParameters(GetStatusesQueryParameters):
    pass


@router.websocket("")
async def stream_statuses(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: QueryGroup[StreamStatusesQueryParameters],
) -> None:
    async for statuses in engine.stream_statuses(filter):
        await socket.send(statuses)
