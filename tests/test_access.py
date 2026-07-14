from ceres.access import resolve_access
from ceres.component import ComponentAccessLevel
from ceres.database import Database
from ceres.group import Group, GroupMembership
from ceres.permission import GroupPermission, PermissionTargetType, UserPermission
from ceres.user import User


async def _setup_database() -> Database:
    database = Database()
    await database.migrate()
    return database


async def test_resolve_access_admin_bypass() -> None:
    """Admin users always get manage regardless of grants."""
    database = await _setup_database()
    admin = await database.users.create(
        User.Create(username="admin", email="admin@test.com", password="hashed", admin=True)
    )
    result = await resolve_access(
        database=database,
        user=admin,
        address_chain=[],
        resolved_access=ComponentAccessLevel.DENY,
        inherited_tags=set(),
    )
    assert result == ComponentAccessLevel.MANAGE


async def test_resolve_access_deny_no_grants() -> None:
    """When default access is deny and no grants exist, returns None."""
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", admin=False)
    )
    result = await resolve_access(
        database=database,
        user=user,
        address_chain=[],
        resolved_access=ComponentAccessLevel.DENY,
        inherited_tags=set(),
    )
    assert result is None


async def test_resolve_access_default_view() -> None:
    """When default access is view and no grants exist, returns view."""
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", admin=False)
    )
    result = await resolve_access(
        database=database,
        user=user,
        address_chain=[],
        resolved_access=ComponentAccessLevel.VIEW,
        inherited_tags=set(),
    )
    assert result == ComponentAccessLevel.VIEW


async def test_resolve_access_direct_user_grant_overrides_default() -> None:
    """A direct user grant takes the max with the default."""
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", admin=False)
    )
    await database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.COMPONENT,
            target="sensors.nortek",
            level=ComponentAccessLevel.OPERATE,
        )
    )
    result = await resolve_access(
        database=database,
        user=user,
        address_chain=["sensors.nortek"],
        resolved_access=ComponentAccessLevel.VIEW,
        inherited_tags=set(),
    )
    assert result == ComponentAccessLevel.OPERATE


async def test_resolve_access_tag_grant() -> None:
    """A user tag grant applies when the component has that tag."""
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", admin=False)
    )
    await database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.TAG,
            target="pressure",
            level=ComponentAccessLevel.OPERATE,
        )
    )
    result = await resolve_access(
        database=database,
        user=user,
        address_chain=["sensors.sbe54"],
        resolved_access=ComponentAccessLevel.DENY,
        inherited_tags={"pressure", "seabird"},
    )
    assert result == ComponentAccessLevel.OPERATE


async def test_resolve_access_group_grant() -> None:
    """A group component grant applies via group membership."""
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", admin=False)
    )
    group = await database.groups.create(Group.Create(name="field-ops"))
    await database.group_memberships.create(
        GroupMembership.Create(user_id=user.id, group_id=group.id)
    )
    await database.group_permissions.create(
        GroupPermission.Create(
            group_id=group.id,
            target_type=PermissionTargetType.COMPONENT,
            target="sensors.nortek",
            level=ComponentAccessLevel.MANAGE,
        )
    )
    result = await resolve_access(
        database=database,
        user=user,
        address_chain=["sensors.nortek"],
        resolved_access=ComponentAccessLevel.DENY,
        inherited_tags=set(),
    )
    assert result == ComponentAccessLevel.MANAGE


async def test_resolve_access_user_all_grant_applies_to_every_component() -> None:
    """A user all-grant applies even to a component absent from `address_chain`."""
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", admin=False)
    )
    await database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.ALL,
            target="",
            level=ComponentAccessLevel.OPERATE,
        )
    )
    result = await resolve_access(
        database=database,
        user=user,
        address_chain=["@sensor.motor", "@sensor"],
        resolved_access=ComponentAccessLevel.DENY,
        inherited_tags=set(),
    )
    assert result == ComponentAccessLevel.OPERATE


async def test_resolve_access_group_all_grant_applies_to_every_component() -> None:
    """A group all-grant applies even to a component absent from `address_chain`."""
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", admin=False)
    )
    group = await database.groups.create(Group.Create(name="field-ops"))
    await database.group_memberships.create(
        GroupMembership.Create(user_id=user.id, group_id=group.id)
    )
    await database.group_permissions.create(
        GroupPermission.Create(
            group_id=group.id,
            target_type=PermissionTargetType.ALL,
            target="",
            level=ComponentAccessLevel.MANAGE,
        )
    )
    result = await resolve_access(
        database=database,
        user=user,
        address_chain=["@sensor.motor", "@sensor"],
        resolved_access=ComponentAccessLevel.DENY,
        inherited_tags=set(),
    )
    assert result == ComponentAccessLevel.MANAGE


async def test_resolve_access_most_permissive_wins() -> None:
    """The max across all sources wins."""
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", admin=False)
    )
    group = await database.groups.create(Group.Create(name="ops"))
    await database.group_memberships.create(
        GroupMembership.Create(user_id=user.id, group_id=group.id)
    )
    await database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.COMPONENT,
            target="sensors.nortek",
            level=ComponentAccessLevel.VIEW,
        )
    )
    await database.group_permissions.create(
        GroupPermission.Create(
            group_id=group.id,
            target_type=PermissionTargetType.COMPONENT,
            target="sensors.nortek",
            level=ComponentAccessLevel.MANAGE,
        )
    )
    result = await resolve_access(
        database=database,
        user=user,
        address_chain=["sensors.nortek"],
        resolved_access=ComponentAccessLevel.VIEW,
        inherited_tags=set(),
    )
    assert result == ComponentAccessLevel.MANAGE


async def test_fetch_access_grants_merges_user_and_group_grants_by_highest_level() -> None:
    """A single fetch merges direct and group grants, keeping the most permissive per target."""
    from ceres.access import fetch_access_grants, resolve_access_from

    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", admin=False)
    )
    first = await database.groups.create(Group.Create(name="first"))
    second = await database.groups.create(Group.Create(name="second"))
    for group in (first, second):
        await database.group_memberships.create(
            GroupMembership.Create(user_id=user.id, group_id=group.id)
        )

    await database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.COMPONENT,
            target="@rack",
            level=ComponentAccessLevel.VIEW,
        )
    )
    await database.group_permissions.create(
        GroupPermission.Create(
            group_id=first.id,
            target_type=PermissionTargetType.COMPONENT,
            target="@rack",
            level=ComponentAccessLevel.OPERATE,
        )
    )
    await database.group_permissions.create(
        GroupPermission.Create(
            group_id=second.id,
            target_type=PermissionTargetType.TAG,
            target="scpr",
            level=ComponentAccessLevel.MANAGE,
        )
    )

    grants = await fetch_access_grants(database, user)

    assert grants.component["@rack"] == ComponentAccessLevel.OPERATE
    assert grants.tag["scpr"] == ComponentAccessLevel.MANAGE

    # The pre-fetched grants resolve per component with no further queries.
    by_address = resolve_access_from(
        grants,
        address_chain=["@rack"],
        resolved_access=ComponentAccessLevel.DENY,
        inherited_tags=set(),
    )
    assert by_address == ComponentAccessLevel.OPERATE

    by_tag = resolve_access_from(
        grants,
        address_chain=["@other"],
        resolved_access=ComponentAccessLevel.DENY,
        inherited_tags={"scpr"},
    )
    assert by_tag == ComponentAccessLevel.MANAGE


async def test_fetch_access_grants_admin_skips_grant_queries() -> None:
    """An admin's grants short-circuit to `admin=True` and resolve to manage everywhere."""
    from ceres.access import fetch_access_grants, resolve_access_from

    database = await _setup_database()
    admin = await database.users.create(
        User.Create(username="admin", email="a@test.com", password="hashed", admin=True)
    )

    grants = await fetch_access_grants(database, admin)
    assert grants.admin is True

    level = resolve_access_from(
        grants,
        address_chain=["@anything"],
        resolved_access=ComponentAccessLevel.DENY,
        inherited_tags=set(),
    )
    assert level == ComponentAccessLevel.MANAGE
