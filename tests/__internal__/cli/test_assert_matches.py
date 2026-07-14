from typing import Any

import pytest

from ceres.__internal__.cli.main import _assert_matches
from ceres.__internal__.cli.shared import CLICommandFailed
from ceres.address import Address, AddressSelector
from ceres.status import Status


class _StubClient:
    """A stub `Client` that returns a fixed list of statuses from `get`."""

    def __init__(self, statuses: list[Status]) -> None:
        self._statuses = statuses

    async def get(self, path: str, *, params: Any = None, result: Any = None) -> list[Status]:
        return self._statuses


async def test_assert_matches_raises_with_quoting_hint_when_nothing_matches() -> None:
    """A selector matching no components fails with a message suggesting quoting."""
    client = _StubClient([])
    address = AddressSelector("sensor")

    with pytest.raises(CLICommandFailed) as excinfo:
        await _assert_matches(client, address)  # type: ignore[arg-type]

    message = str(excinfo.value)
    assert "No components match 'sensor'" in message
    assert "quote" in message


async def test_assert_matches_passes_when_at_least_one_component_matches() -> None:
    """A selector matching at least one component does not raise."""
    status = Status(address=Address("@sensor"), running=True)
    client = _StubClient([status])
    address = AddressSelector("sensor")

    await _assert_matches(client, address)  # type: ignore[arg-type]
