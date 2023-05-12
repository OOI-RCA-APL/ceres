from datetime import timedelta

import pytest

from ceres.schedule import IntervalSchedule


@pytest.mark.parametrize(
    ["schedule", "expected"],
    [
        [
            IntervalSchedule(
                interval=timedelta(seconds=5),
            ),
            [timedelta(seconds=5)] * 10,
        ],
        [
            IntervalSchedule(
                interval=timedelta(seconds=1),
                multiplier=2,
            ),
            [
                timedelta(seconds=1),
                timedelta(seconds=2),
                timedelta(seconds=4),
                timedelta(seconds=8),
                timedelta(seconds=16),
                timedelta(seconds=32),
                timedelta(seconds=64),
            ],
        ],
        [
            IntervalSchedule(
                interval=timedelta(seconds=1),
                multiplier=2,
                max=timedelta(seconds=30),
            ),
            [
                timedelta(seconds=1),
                timedelta(seconds=2),
                timedelta(seconds=4),
                timedelta(seconds=8),
                timedelta(seconds=16),
                timedelta(seconds=30),
                timedelta(seconds=30),
            ],
        ],
        [
            IntervalSchedule(
                interval=timedelta(seconds=16),
                multiplier=0.5,
            ),
            [
                timedelta(seconds=16),
                timedelta(seconds=8),
                timedelta(seconds=4),
                timedelta(seconds=2),
                timedelta(seconds=1),
                timedelta(seconds=0.5),
            ],
        ],
        [
            IntervalSchedule(
                interval=timedelta(seconds=16),
                multiplier=0.5,
                min=timedelta(seconds=3),
            ),
            [
                timedelta(seconds=16),
                timedelta(seconds=8),
                timedelta(seconds=4),
                timedelta(seconds=3),
                timedelta(seconds=3),
            ],
        ],
    ],
)
def test_interval_schedule(schedule: IntervalSchedule, expected: list[timedelta]) -> None:
    trigger = schedule.as_trigger()
    start = trigger.start
    now = start - timedelta(seconds=1)
    assert trigger.next(now=now) == start

    now = start

    for delay in expected:
        next = trigger.next(now=now + timedelta(milliseconds=1))
        assert next is not None
        assert next == now + delay
        now = next
