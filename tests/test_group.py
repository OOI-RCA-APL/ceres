from ceres import Group, GroupMembership
from tests import testing


async def test_group_name_filtering() -> None:
    await testing.execute_string_filter_test(Group, "name")


async def test_group_id_filtering() -> None:
    await testing.execute_id_filter_test(Group, "id")


async def test_group_membership_user_id_filtering() -> None:
    await testing.execute_id_filter_test(GroupMembership, "user_id")


async def test_group_membership_group_id_filtering() -> None:
    await testing.execute_id_filter_test(GroupMembership, "group_id")
