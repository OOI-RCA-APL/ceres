from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field

from ceres._internal.app.shared import CurrentEngine, CurrentSocket
from ceres.alert import Alert, AlertFilter, Level

router = APIRouter(prefix="/alerts", tags=["alerts"])


class GetAlertsQueryParameters(AlertFilter):
    level: Level | None = None
    code: str | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@router.get("")
async def get_alerts(
    engine: CurrentEngine,
    filter: Annotated[GetAlertsQueryParameters, Query()],
) -> list[Alert]:
    return await engine.alerts.get_all(filter)


class FollowAlertsQueryParameters(GetAlertsQueryParameters):
    pass


@router.websocket("")
async def follow_alerts(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[FollowAlertsQueryParameters, Query()],
) -> None:
    async for alert in engine.alerts.follow(filter):
        await socket.send(alert)
