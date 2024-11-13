from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field

from ceres._internal.app.shared import CurrentEngine, CurrentSocket, assert_found
from ceres.logs import LogEntry, LogEntryFilter

router = APIRouter(prefix="/log-entries", tags=["logs"])


@router.get("/{id}")
async def get_log_entry(engine: CurrentEngine, id: UUID) -> LogEntry:
    return assert_found(await engine.log.get(id=id))


class GetLogEntriesQueryParameters(LogEntryFilter):
    limit: int = Field(default=100, ge=0, le=1000)


@router.get("")
async def get_log_entries(
    engine: CurrentEngine,
    filter: Annotated[GetLogEntriesQueryParameters, Query()],
) -> list[LogEntry]:
    return await engine.log.get_all(filter)


class FollowLogEntriesQueryParameters(GetLogEntriesQueryParameters):
    pass


@router.websocket("")
async def follow_log_entries(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[FollowLogEntriesQueryParameters, Query()],
) -> None:
    async for entry in engine.log.follow(filter):
        await socket.send(entry)
