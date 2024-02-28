from fastapi import APIRouter
from pydantic import Field

from ceres.alert import Alert, Level
from ceres.filter import AlertFilter
from ceres.internal.app.shared import CurrentEngine, CurrentSocket, QueryGroup

router = APIRouter(prefix="/alerts", tags=["alerts"])


class GetAlertsQueryParameters(AlertFilter):
    level: Level | None = None
    code: str | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@router.get("")
async def get_alerts(
    engine: CurrentEngine,
    filter: QueryGroup[GetAlertsQueryParameters],
) -> list[Alert]:
    return await engine.get_alerts(filter)


class StreamAlertsQueryParameters(GetAlertsQueryParameters):
    pass


@router.websocket("")
async def stream_alerts(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: QueryGroup[StreamAlertsQueryParameters],
) -> None:
    async for alert in engine.stream_alerts(filter):
        await socket.send(alert)
