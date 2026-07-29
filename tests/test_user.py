from ceres import User
from tests import testing


async def test_user_username_filtering():
    await testing.execute_string_filter_test(User, "username")


async def test_user_email_filtering():
    await testing.execute_email_filter_test(User, "email")


async def test_user_admin_filtering():
    await testing.execute_boolean_filter_test(User, "admin")


async def test_disabled_filtering():
    await testing.execute_boolean_filter_test(User, "disabled")
