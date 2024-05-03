from fastapi import APIRouter

from ceres._internal.app.shared import CurrentEngine, QueryGroup
from ceres.statistics import Statistics, StatisticsFilter

router = APIRouter(prefix="/statistics", tags=["statistics"])


class GetStatisticsQueryParameters(StatisticsFilter):
    pass


@router.get("")
async def get_statistics(
    engine: CurrentEngine,
    filter: QueryGroup[GetStatisticsQueryParameters],
) -> list[Statistics]:
    return await engine.statistics.get_all(filter)
