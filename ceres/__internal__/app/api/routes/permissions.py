from uuid import UUID

from ceres.__internal__.app.shared import (
    ADMIN,
    VIEWER,
    CurrentEngine,
    CurrentUser,
    Router,
    assert_found,
    get_component_access,
)
from ceres.address import Address
from ceres.component import ComponentAccessLevel
from ceres.data import DataObject
from ceres.error import NotFoundError, NotPermittedError
from ceres.permission import (
    GroupPermission,
    PermissionTargetType,
    UserPermission,
)
from ceres.user import UserRole

router = Router(prefix="/permissions", tags=["permissions"])


@router.get("/user/{user_id:uuid}", dependencies=[VIEWER])
async def get_user_permissions(
    engine: CurrentEngine,
    user: CurrentUser,
    user_id: UUID,
) -> list[UserPermission]:
    if user is not None and user.role < UserRole.ADMIN and user.id != user_id:
        raise NotPermittedError()

    return await engine.database.user_permissions.where(user_id=user_id)


@router.get("/group/{group_id:uuid}", dependencies=[ADMIN])
async def get_group_permissions(
    engine: CurrentEngine,
    group_id: UUID,
) -> list[GroupPermission]:
    return await engine.database.group_permissions.where(group_id=group_id)


class UserPermissionData(DataObject):
    target_type: PermissionTargetType
    target: str
    level: ComponentAccessLevel


@router.put("/user/{user_id:uuid}", dependencies=[ADMIN])
async def set_user_permission(
    engine: CurrentEngine,
    user_id: UUID,
    data: UserPermissionData,
) -> UserPermission:
    existing = await engine.database.user_permissions.where(
        user_id=user_id,
        target_type=data.target_type,
        target=data.target,
    ).first()

    if existing is not None:
        await engine.database.user_permissions.where(
            user_id=user_id,
            target_type=data.target_type,
            target=data.target,
        ).update(UserPermission.Update(level=data.level))
        return assert_found(
            await engine.database.user_permissions.where(
                user_id=user_id,
                target_type=data.target_type,
                target=data.target,
            ).first()
        )

    return await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user_id,
            target_type=data.target_type,
            target=data.target,
            level=data.level,
        )
    )


class DeletePermissionData(DataObject):
    target_type: PermissionTargetType
    target: str


@router.delete("/user/{user_id:uuid}", dependencies=[ADMIN])
async def delete_user_permission(
    engine: CurrentEngine,
    user_id: UUID,
    data: DeletePermissionData,
) -> int:
    return await engine.database.user_permissions.where(
        user_id=user_id,
        target_type=data.target_type,
        target=data.target,
    ).delete()


class GroupPermissionData(DataObject):
    target_type: PermissionTargetType
    target: str
    level: ComponentAccessLevel


@router.put("/group/{group_id:uuid}", dependencies=[ADMIN])
async def set_group_permission(
    engine: CurrentEngine,
    group_id: UUID,
    data: GroupPermissionData,
) -> GroupPermission:
    existing = await engine.database.group_permissions.where(
        group_id=group_id,
        target_type=data.target_type,
        target=data.target,
    ).first()

    if existing is not None:
        await engine.database.group_permissions.where(
            group_id=group_id,
            target_type=data.target_type,
            target=data.target,
        ).update(GroupPermission.Update(level=data.level))
        return assert_found(
            await engine.database.group_permissions.where(
                group_id=group_id,
                target_type=data.target_type,
                target=data.target,
            ).first()
        )

    return await engine.database.group_permissions.create(
        GroupPermission.Create(
            group_id=group_id,
            target_type=data.target_type,
            target=data.target,
            level=data.level,
        )
    )


@router.delete("/group/{group_id:uuid}", dependencies=[ADMIN])
async def delete_group_permission(
    engine: CurrentEngine,
    group_id: UUID,
    data: DeletePermissionData,
) -> int:
    return await engine.database.group_permissions.where(
        group_id=group_id,
        target_type=data.target_type,
        target=data.target,
    ).delete()


class EffectiveAccessResult(DataObject):
    level: ComponentAccessLevel | None


@router.get("/effective/{user_id:uuid}/{address:path}", dependencies=[VIEWER])
async def get_effective_access(
    engine: CurrentEngine,
    user: CurrentUser,
    user_id: UUID,
    address: Address,
) -> EffectiveAccessResult:
    if user is not None and user.role < UserRole.ADMIN and user.id != user_id:
        raise NotPermittedError()

    target_user = await engine.database.users.get(user_id)
    if target_user is None:
        raise NotFoundError()

    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()

    level = await get_component_access(engine, target_user, component)
    return EffectiveAccessResult(level=level)
