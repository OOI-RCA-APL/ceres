from typing import Annotated

from fastapi import Query

from ceres._internal.app.shared import CurrentEngine, Router
from ceres.statistics import Statistics, StatisticsFilter

router = Router(prefix="/statistics", tags=["statistics"])


@router.get("")
async def get_statistics(
    engine: CurrentEngine,
    filter: Annotated[StatisticsFilter, Query()],
) -> list[Statistics]:
    return await engine.statistics.get_all(filter)
