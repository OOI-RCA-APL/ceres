from ceres import Level, LogEntry
from ceres.config import LoggingConfig
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
