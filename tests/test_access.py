from uuid import UUID, uuid4

from ceres.access import (
    AccessGrants,
    AccessSource,
    Grant,
    GrantOrigin,
    fetch_access_grants,
    resolve_access,
    resolve_access_detail_from,
    resolve_access_from,
)
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

    assert grants.component["@rack"].level == ComponentAccessLevel.OPERATE
    assert grants.tag["scpr"].level == ComponentAccessLevel.MANAGE

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


def _grants(
    *,
    admin: bool = False,
    everything: Grant | None = None,
    component: dict[str, Grant] | None = None,
    tag: dict[str, Grant] | None = None,
) -> AccessGrants:
    return AccessGrants(
        admin=admin,
        everything=everything,
        component=component or {},
        tag=tag or {},
    )


def _user_grant(level: ComponentAccessLevel) -> Grant:
    return Grant(level=level, origin=GrantOrigin.USER)


def _group_grant(level: ComponentAccessLevel, group_id: UUID) -> Grant:
    return Grant(level=level, origin=GrantOrigin.GROUP, group_id=group_id)


class TestResolveAccessDetail:
    """`resolve_access_detail_from` reports which input produced the effective level."""

    def test_admin_is_reported_as_admin(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(admin=True),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.DENY,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.level == ComponentAccessLevel.MANAGE
        assert resolved.source == AccessSource.ADMIN

    def test_default_is_reported_when_no_grant_matches(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.level == ComponentAccessLevel.VIEW
        assert resolved.source == AccessSource.DEFAULT

    def test_no_access_returns_none(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.DENY,
            inherited_tags=set(),
        )
        assert resolved is None

    def test_component_grant_is_reported(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(component={"@sensor": _user_grant(ComponentAccessLevel.OPERATE)}),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.level == ComponentAccessLevel.OPERATE
        assert resolved.source == AccessSource.COMPONENT

    def test_ancestor_grant_is_reported_as_a_component_grant(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(component={"@rack": _user_grant(ComponentAccessLevel.MANAGE)}),
            address_chain=["@rack.sensor", "@rack"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.source == AccessSource.COMPONENT

    def test_tag_grant_is_reported(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(tag={"hardware": _user_grant(ComponentAccessLevel.OPERATE)}),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags={"hardware"},
        )
        assert resolved is not None
        assert resolved.source == AccessSource.TAG

    def test_all_grant_is_reported(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(everything=_user_grant(ComponentAccessLevel.MANAGE)),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.source == AccessSource.ALL

    def test_a_grant_tying_the_default_is_reported_over_the_default(self) -> None:
        """A redundant grant still shows as the source, since removing it is what matters."""
        resolved = resolve_access_detail_from(
            _grants(component={"@sensor": _user_grant(ComponentAccessLevel.VIEW)}),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.level == ComponentAccessLevel.VIEW
        assert resolved.source == AccessSource.COMPONENT

    def test_component_grant_wins_a_tie_against_a_tag_grant(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(
                component={"@sensor": _user_grant(ComponentAccessLevel.OPERATE)},
                tag={"hardware": _user_grant(ComponentAccessLevel.OPERATE)},
            ),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags={"hardware"},
        )
        assert resolved is not None
        assert resolved.source == AccessSource.COMPONENT

    def test_the_highest_level_still_wins_over_specificity(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(
                component={"@sensor": _user_grant(ComponentAccessLevel.VIEW)},
                tag={"hardware": _user_grant(ComponentAccessLevel.MANAGE)},
            ),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags={"hardware"},
        )
        assert resolved is not None
        assert resolved.level == ComponentAccessLevel.MANAGE
        assert resolved.source == AccessSource.TAG

    def test_level_matches_resolve_access_from(self) -> None:
        """The detailed resolver must not disagree with the level-only one."""
        grants = _grants(
            component={"@rack": _user_grant(ComponentAccessLevel.OPERATE)},
            tag={"hardware": _user_grant(ComponentAccessLevel.VIEW)},
            everything=_user_grant(ComponentAccessLevel.VIEW),
        )
        arguments = {
            "address_chain": ["@rack.sensor", "@rack"],
            "resolved_access": ComponentAccessLevel.DENY,
            "inherited_tags": {"hardware"},
        }
        resolved = resolve_access_detail_from(grants, **arguments)
        assert resolved is not None
        assert resolved.level == resolve_access_from(grants, **arguments)

    def test_group_grant_reports_the_group_it_came_from(self) -> None:
        group_id = uuid4()
        resolved = resolve_access_detail_from(
            _grants(component={"@sensor": _group_grant(ComponentAccessLevel.OPERATE, group_id)}),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.source == AccessSource.COMPONENT
        assert resolved.origin == GrantOrigin.GROUP
        assert resolved.group_id == group_id

    def test_user_grant_reports_no_group(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(component={"@sensor": _user_grant(ComponentAccessLevel.OPERATE)}),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.origin == GrantOrigin.USER
        assert resolved.group_id is None

    def test_the_default_reports_no_origin(self) -> None:
        resolved = resolve_access_detail_from(
            _grants(),
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.VIEW,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.origin is None
        assert resolved.group_id is None

    def test_a_user_grant_wins_a_tie_against_a_group_grant(self) -> None:
        """Ties favour the user's own grant, since that is the one to remove to change access."""
        grants = AccessGrants()
        grants._add(
            PermissionTargetType.COMPONENT,
            "@sensor",
            _group_grant(ComponentAccessLevel.OPERATE, uuid4()),
        )
        grants._add(
            PermissionTargetType.COMPONENT,
            "@sensor",
            _user_grant(ComponentAccessLevel.OPERATE),
        )

        resolved = resolve_access_detail_from(
            grants,
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.DENY,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.origin == GrantOrigin.USER

    async def test_group_provenance_survives_a_real_fetch(self) -> None:
        """Provenance is populated by `fetch_access_grants`, not just by hand-built grants."""
        database = await _setup_database()
        user = await database.users.create(
            User.Create(username="member", email="m@test.com", password="hashed", admin=False)
        )
        group = await database.groups.create(Group.Create(name="field-ops"))
        await database.group_memberships.create(
            GroupMembership.Create(user_id=user.id, group_id=group.id)
        )
        await database.group_permissions.create(
            GroupPermission.Create(
                group_id=group.id,
                target_type=PermissionTargetType.COMPONENT,
                target="@sensor",
                level=ComponentAccessLevel.MANAGE,
            )
        )

        grants = await fetch_access_grants(database, user)
        resolved = resolve_access_detail_from(
            grants,
            address_chain=["@sensor"],
            resolved_access=ComponentAccessLevel.DENY,
            inherited_tags=set(),
        )
        assert resolved is not None
        assert resolved.origin == GrantOrigin.GROUP
        assert resolved.group_id == group.id
