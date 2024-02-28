from fastapi import APIRouter

from ceres.filter import StatisticsFilter
from ceres.internal.app.shared import CurrentEngine, QueryGroup
from ceres.statistics import Statistics

router = APIRouter(prefix="/statistics", tags=["statistics"])


class GetStatisticsQueryParameters(StatisticsFilter):
    pass


@router.get("")
async def get_statistics(
    engine: CurrentEngine,
    filter: QueryGroup[GetStatisticsQueryParameters],
) -> list[Statistics]:
    return await engine.get_statistics(filter)
