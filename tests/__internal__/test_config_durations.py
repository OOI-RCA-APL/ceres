"""Duration spellings accepted by the native configuration types.

The engine accepts numbers, ISO 8601 intervals, clock text, and its own suffix grammar
(`30d`) for configured durations so the native `ServerConfig` must parse every
spelling a deployed `ceres.yaml` can carry.
"""

from datetime import timedelta

import pytest

from ceres.config import Config
from ceres.data import validate

CASES = [
    ("900", timedelta(minutes=15)),
    ("PT30M", timedelta(minutes=30)),
    ("P1DT2H", timedelta(days=1, hours=2)),
    ("01:30:00", timedelta(hours=1, minutes=30)),
    ("30d", timedelta(days=30)),
    ("12h", timedelta(hours=12)),
    ("30m", timedelta(minutes=30)),
    ("45s", timedelta(seconds=45)),
    ("250ms", timedelta(milliseconds=250)),
    ("1.5h", timedelta(minutes=90)),
    ("30D", timedelta(days=30)),
]


def _configured(duration: str) -> Config:
    return validate(
        Config,
        {
            "components": [],
            "server": {
                "authentication": {
                    "secret": "an-adequately-long-test-signing-secret",
                    "duration": duration,
                }
            },
        },
    )


@pytest.mark.parametrize(("spelling", "expected"), CASES)
def test_every_duration_spelling_loads(spelling: str, expected: timedelta) -> None:
    config = _configured(spelling)
    authentication = config.server.authentication
    assert authentication is not None
    assert authentication.duration == expected


@pytest.mark.parametrize("rejected", ["week", "5x", "d", "-5s", ""])
def test_invalid_durations_refuse(rejected: str) -> None:
    with pytest.raises(ValueError):
        _configured(rejected)
