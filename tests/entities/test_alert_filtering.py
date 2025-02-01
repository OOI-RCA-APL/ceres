from ceres import Alert
from tests import testing


async def test_alert_id_filtering():
    await testing.execute_id_filter_test(Alert)


async def test_alert_address_filtering():
    await testing.execute_address_filter_test(Alert)


async def test_alert_timestamp_filtering():
    await testing.execute_timestamp_filter_test(Alert)


async def test_alert_level_filtering():
    await testing.execute_enum_filter_test(Alert, "level", Alert.Level)


async def test_alert_type_filtering():
    await testing.execute_string_filter_test(Alert, "type")


async def test_alert_data_filtering():
    await testing.execute_json_data_filter_test(Alert, "data")
