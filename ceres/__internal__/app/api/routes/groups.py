from uuid import UUID

from ceres.__internal__.app.shared import (
    ADMIN,
    VIEWER,
    CurrentEngine,
    Router,
    assert_found,
)
from ceres.group import Group, GroupMembership

router = Router(prefix="/groups", tags=["groups"])


@router.get("/{id:uuid}", dependencies=[VIEWER])
async def get_group(engine: CurrentEngine, id: UUID) -> Group:
    return assert_found(await engine.database.groups.get(id))


@router.get("", dependencies=[VIEWER])
async def get_groups(engine: CurrentEngine) -> list[Group]:
    return await engine.database.groups.where()


@router.get("/count", dependencies=[VIEWER])
async def count_groups(engine: CurrentEngine) -> int:
    return await engine.database.groups.where().count()


@router.post("", dependencies=[ADMIN])
async def create_group(engine: CurrentEngine, data: Group.Create) -> Group:
    return await engine.database.groups.create(data)


@router.patch("/{id:uuid}", dependencies=[ADMIN])
async def update_group(engine: CurrentEngine, id: UUID, data: Group.Update) -> int:
    return await engine.database.groups.where(id=id).update(data)


@router.delete("/{id:uuid}", dependencies=[ADMIN])
async def delete_group(engine: CurrentEngine, id: UUID) -> int:
    return await engine.database.groups.where(id=id).delete()


@router.get("/{id:uuid}/members", dependencies=[VIEWER])
async def get_group_members(engine: CurrentEngine, id: UUID) -> list[GroupMembership]:
    assert_found(await engine.database.groups.get(id))
    return await engine.database.group_memberships.where(group_id=id)


@router.post("/{id:uuid}/members", dependencies=[ADMIN])
async def add_group_member(
    engine: CurrentEngine,
    id: UUID,
    data: GroupMembership.Create,
) -> GroupMembership:
    assert_found(await engine.database.groups.get(id))
    return await engine.database.group_memberships.create(data)


@router.delete("/{id:uuid}/members/{user_id:uuid}", dependencies=[ADMIN])
async def remove_group_member(
    engine: CurrentEngine,
    id: UUID,
    user_id: UUID,
) -> int:
    return await engine.database.group_memberships.where(
        user_id=user_id,
        group_id=id,
    ).delete()
