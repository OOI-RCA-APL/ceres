from typing import Annotated

from fastapi import Query

from ceres.__internal__.app.shared import AUTHENTICATED, CurrentEngine, Router
from ceres.statistics import Statistics, StatisticsFilter

router = Router(prefix="/statistics", tags=["statistics"], dependencies=[AUTHENTICATED])


@router.get("")
async def get_statistics(
    engine: CurrentEngine,
    filter: Annotated[StatisticsFilter, Query()],
) -> list[Statistics]:
    """Return statistics matching the given filter."""
    return await engine.statistics.get_all(filter)
