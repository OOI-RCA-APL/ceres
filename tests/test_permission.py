from ceres.permission import (
    GroupPermission,
    PermissionTargetType,
    UserPermission,
)
from tests import testing


async def test_permission_target_type_values() -> None:
    assert PermissionTargetType.COMPONENT == "component"
    assert PermissionTargetType.TAG == "tag"


async def test_user_permission_id_filtering() -> None:
    await testing.execute_id_filter_test(UserPermission, "user_id")


async def test_group_permission_id_filtering() -> None:
    await testing.execute_id_filter_test(GroupPermission, "group_id")
