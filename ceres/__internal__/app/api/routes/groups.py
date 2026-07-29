from uuid import UUID

from ceres.__internal__.app.shared import (
    ADMIN,
    AUTHENTICATED,
    CurrentEngine,
    Router,
    assert_found,
)
from ceres.group import Group, GroupMembership

router = Router(prefix="/groups", tags=["groups"])
user_router = Router(tags=["group-memberships"])


@router.get("/{id:uuid}", dependencies=[AUTHENTICATED])
async def get_group(engine: CurrentEngine, id: UUID) -> Group:
    return assert_found(await engine.database.groups.get(id))


@router.get("", dependencies=[AUTHENTICATED])
async def get_groups(engine: CurrentEngine) -> list[Group]:
    return await engine.database.groups.where()


@router.get("/count", dependencies=[AUTHENTICATED])
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


@router.get("/{id:uuid}/members", dependencies=[AUTHENTICATED])
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


@user_router.get("/users/{user_id:uuid}/group-memberships", dependencies=[AUTHENTICATED])
async def get_user_group_memberships(
    engine: CurrentEngine,
    user_id: UUID,
) -> list[GroupMembership]:
    """Return all group memberships for a user."""
    return await engine.database.group_memberships.where(user_id=user_id)


@user_router.post(
    "/users/{user_id:uuid}/group-memberships/{group_id:uuid}",
    dependencies=[ADMIN],
)
async def add_user_to_group(
    engine: CurrentEngine,
    user_id: UUID,
    group_id: UUID,
) -> GroupMembership:
    """Add a user to a group."""
    assert_found(await engine.database.groups.get(group_id))
    return await engine.database.group_memberships.create(
        GroupMembership(user_id=user_id, group_id=group_id),
    )


@user_router.delete(
    "/users/{user_id:uuid}/group-memberships/{group_id:uuid}",
    dependencies=[ADMIN],
)
async def remove_user_from_group(
    engine: CurrentEngine,
    user_id: UUID,
    group_id: UUID,
) -> int:
    """Remove a user from a group."""
    return await engine.database.group_memberships.where(
        user_id=user_id,
        group_id=group_id,
    ).delete()
