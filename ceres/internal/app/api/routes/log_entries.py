from fastapi import APIRouter
from pydantic import Field

from ceres.alert import Level
from ceres.filter import LogEntryFilter
from ceres.internal.app.shared import CurrentEngine, CurrentSocket, QueryGroup
from ceres.logs import LogEntry

router = APIRouter(prefix="/log-entries", tags=["logs"])


class GetLogEntriesQueryParameters(LogEntryFilter):
    level: Level | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@router.get("")
async def get_log_entries(
    engine: CurrentEngine,
    filter: QueryGroup[GetLogEntriesQueryParameters],
) -> list[LogEntry]:
    return await engine.get_log_entries(filter)


class StreamLogEntriesQueryParameters(GetLogEntriesQueryParameters):
    pass


@router.websocket("")
async def stream_log_entries(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: QueryGroup[StreamLogEntriesQueryParameters],
) -> None:
    async for entry in engine.stream_log_entries(filter):
        await socket.send(entry)
