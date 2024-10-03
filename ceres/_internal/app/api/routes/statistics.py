from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ceres._internal.app.shared import CurrentEngine
from ceres.statistics import Statistics, StatisticsFilter

router = APIRouter(prefix="/statistics", tags=["statistics"])


class GetStatisticsQueryParameters(StatisticsFilter):
    pass


@router.get("")
async def get_statistics(
    engine: CurrentEngine,
    filter: Annotated[GetStatisticsQueryParameters, Query()],
) -> list[Statistics]:
    return await engine.statistics.get_all(filter)
