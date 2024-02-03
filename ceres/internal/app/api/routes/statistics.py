from typing import Annotated

from fastapi import APIRouter, Depends

from ceres.filter import StatisticsFilter
from ceres.internal.app.shared import CurrentEngine
from ceres.statistics import Statistics

router = APIRouter(prefix="/statistics", tags=["statistics"])


class GetStatisticsQueryParameters(StatisticsFilter):
    pass


@router.get("")
async def get_statistics(
    engine: CurrentEngine,
    filter: Annotated[GetStatisticsQueryParameters, Depends()],
) -> list[Statistics]:
    return await engine.get_statistics(filter)
