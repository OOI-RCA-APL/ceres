from collections.abc import Iterable
from typing import override

from ceres import Component
from ceres.config import MessagePrunerConfig, PrunerConfig
from ceres.message import MessageFilter
from ceres.schedule import CronSchedule


class PrunedComponent(Component):
    @override
    def __static_pruners__(self) -> Iterable[PrunerConfig]:
        return (
            MessagePrunerConfig(
                name="old-messages",
                schedule=CronSchedule(crontab="0 12 * * *"),
                filter=MessageFilter(),
            ),
        )


def test_component_with_pruner() -> None:
    component = PrunedComponent()

    pruner = component.system.pruners.get("old-messages")

    assert pruner is not None
    assert pruner.name == "old-messages"
