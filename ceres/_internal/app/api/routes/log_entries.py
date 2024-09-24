from __future__ import annotations

from fastapi import APIRouter
from pydantic import Field

from ceres._internal.app.shared import CurrentEngine, CurrentSocket, QueryGroup
from ceres.level import Level
from ceres.logs import LogEntry, LogEntryFilter

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
    return await engine.log.get_all(filter)


class FollowLogEntriesQueryParameters(GetLogEntriesQueryParameters):
    pass


@router.websocket("")
async def follow_log_entries(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: QueryGroup[FollowLogEntriesQueryParameters],
) -> None:
    async for entry in engine.log.follow(filter):
        await socket.send(entry)
