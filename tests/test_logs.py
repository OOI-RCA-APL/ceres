import asyncio
from typing import Any

import pytest

from ceres import Component, Level, LogEntry
from ceres.concurrency import spawn
from ceres.config import LoggingConfig
from ceres.event import LogEvent
from ceres.logs import capture_logs
from tests import testing


async def test_log_id_filtering():
    await testing.execute_id_filter_test(LogEntry)


async def test_log_address_filtering():
    await testing.execute_address_filter_test(LogEntry)


async def test_log_timestamp_filtering():
    await testing.execute_timestamp_filter_test(LogEntry)


async def test_log_level_filtering():
    await testing.execute_enum_filter_test(LogEntry, "level", LogEntry.Level, comparison=True)


async def test_log_content_filtering():
    await testing.execute_string_filter_test(LogEntry, "content", prefixed=False)


def test_merging_logging_configs_overlays_only_explicitly_set_fields():
    """A child's explicit settings win, and everything it leaves unset is inherited."""
    inherited = LoggingConfig(output="warning", events=False)
    local = LoggingConfig(store="error")

    merged = inherited.merged(local)
    assert type(merged) is LoggingConfig
    assert merged.output == Level.WARNING
    assert merged.store == Level.ERROR
    assert merged.events is False


async def test_a_capture_takes_its_task_and_threads_entries_and_no_others() -> None:
    component = Component(__with_name__="abc")
    log = component.system.log
    go = asyncio.Event()

    async def elsewhere() -> None:
        await go.wait()
        log.info("outside")

    other = asyncio.create_task(elsewhere())
    with component.system.events.every(LogEvent).read() as reader:
        with capture_logs(limit=2) as capture:
            log.info("a")
            await spawn(log.warning, "b")
            go.set()
            await other
            log.error("c")

        log.info("after")
        heard: list[Any] = reader.clear()

    assert [entry.content for entry in capture.entries] == ["a", "b"]
    assert capture.counts == {Level.INFO: 1, Level.WARNING: 1, Level.ERROR: 1}
    assert capture.truncated
    assert [event.entry.content for event in heard] == ["outside", "after"]


async def test_a_capture_ends_when_its_block_raises() -> None:
    component = Component(__with_name__="abc")
    with pytest.raises(RuntimeError), capture_logs():
        raise RuntimeError("abc")

    with component.system.events.every(LogEvent).read() as reader:
        component.system.log.info("a")
        heard: list[Any] = reader.clear()

    assert len(heard) == 1
