from ceres import Setting
from tests import testing


async def test_setting_user_id_filtering():
    await testing.execute_id_filter_test(Setting, "user_id")


async def test_setting_name_filtering():
    await testing.execute_string_filter_test(Setting, "name")
