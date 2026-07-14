from typing import Self
from uuid import UUID

from pydantic import model_validator

from ceres.__internal__.app.shared import (
    ADMIN,
    SELF_OR_ADMIN,
    CurrentEngine,
    Router,
    get_component_access,
    get_components_access,
)
from ceres.address import Address
from ceres.component import ComponentAccessLevel
from ceres.data import DataObject
from ceres.error import NotFoundError
from ceres.permission import (
    GroupPermission,
    PermissionTargetType,
    UserPermission,
)

router = Router(prefix="/permissions", tags=["permissions"])


@router.get("/user/{user_id:uuid}", dependencies=[SELF_OR_ADMIN])
async def get_user_permissions(
    engine: CurrentEngine,
    user_id: UUID,
) -> list[UserPermission]:
    return await engine.database.user_permissions.where(user_id=user_id)


@router.get("/group/{group_id:uuid}", dependencies=[ADMIN])
async def get_group_permissions(
    engine: CurrentEngine,
    group_id: UUID,
) -> list[GroupPermission]:
    return await engine.database.group_permissions.where(group_id=group_id)


class PermissionTargetData(DataObject):
    target_type: PermissionTargetType
    target: str = ""

    @model_validator(mode="after")
    def _validate_target(self) -> Self:
        if self.target_type == PermissionTargetType.ALL:
            if self.target:
                raise ValueError("target must be empty for 'all' permissions")
        elif self.target_type == PermissionTargetType.COMPONENT:
            Address(self.target)
        elif not self.target:
            raise ValueError("target must not be empty for 'tag' permissions")

        return self


class UserPermissionData(PermissionTargetData):
    level: ComponentAccessLevel


@router.put("/user/{user_id:uuid}", dependencies=[ADMIN])
async def set_user_permission(
    engine: CurrentEngine,
    user_id: UUID,
    data: UserPermissionData,
) -> UserPermission:
    return await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user_id,
            target_type=data.target_type,
            target=data.target,
            level=data.level,
        ),
        upsert=True,
    )


class DeletePermissionData(PermissionTargetData):
    pass


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


class GroupPermissionData(PermissionTargetData):
    level: ComponentAccessLevel


@router.put("/group/{group_id:uuid}", dependencies=[ADMIN])
async def set_group_permission(
    engine: CurrentEngine,
    group_id: UUID,
    data: GroupPermissionData,
) -> GroupPermission:
    return await engine.database.group_permissions.create(
        GroupPermission.Create(
            group_id=group_id,
            target_type=data.target_type,
            target=data.target,
            level=data.level,
        ),
        upsert=True,
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


class ComponentEffectiveAccess(DataObject):
    """Effective access level a user holds on a single component."""

    address: Address
    level: ComponentAccessLevel


@router.get("/effective/{user_id:uuid}", dependencies=[SELF_OR_ADMIN])
async def get_all_effective_access(
    engine: CurrentEngine,
    user_id: UUID,
) -> list[ComponentEffectiveAccess]:
    """Resolve the effective access level for every component the target user can access.

    Components the user has no access to are omitted.

    Raises:
        NotFoundError: If the target user does not exist.
        NotPermittedError: If a non-admin caller queries another user.
    """
    target_user = await engine.database.users.get(user_id)
    if target_user is None:
        raise NotFoundError()

    access = await get_components_access(engine, target_user, engine.get_components())

    return [
        ComponentEffectiveAccess(address=address, level=level)
        for address, level in access.items()
        if level is not None
    ]


@router.get("/effective/{user_id:uuid}/{address:path}", dependencies=[SELF_OR_ADMIN])
async def get_effective_access(
    engine: CurrentEngine,
    user_id: UUID,
    address: Address,
) -> EffectiveAccessResult:
    target_user = await engine.database.users.get(user_id)
    if target_user is None:
        raise NotFoundError()

    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()

    level = await get_component_access(engine, target_user, component)
    return EffectiveAccessResult(level=level)
