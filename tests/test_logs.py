from ceres import LogEntry
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
