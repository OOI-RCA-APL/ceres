from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ceres.component import ComponentAccessLevel
from ceres.data import StrEnum
from ceres.permission import PermissionTargetType

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.database import Database
    from ceres.permission import GroupPermission, UserPermission
    from ceres.user import User

__all__ = [
    "AccessGrants",
    "AccessSource",
    "Grant",
    "GrantOrigin",
    "ResolvedAccess",
    "fetch_access_grants",
    "resolve_access",
    "resolve_access_detail_from",
    "resolve_access_from",
]


class AccessSource(StrEnum):
    """Which input decided a component's effective access level."""

    ADMIN = "admin"
    """The user is an admin, which grants `MANAGE` everywhere."""
    DEFAULT = "default"
    """The component's default access level, inherited from config when not granted."""
    COMPONENT = "component"
    """A grant targeting the component or one of its ancestors."""
    TAG = "tag"
    """A grant targeting one of the component's inherited tags."""
    ALL = "all"
    """A grant targeting every component."""


class GrantOrigin(StrEnum):
    """Whether a grant was held by the user directly or inherited from a group."""

    USER = "user"
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class Grant:
    """A single merged grant, keeping enough provenance to explain where it came from."""

    level: ComponentAccessLevel
    """The level this grant confers."""

    origin: GrantOrigin
    """Whether the grant is the user's own or inherited from a group."""

    group_id: UUID | None = None
    """The group that supplied the grant, when `origin` is `GROUP`."""


@dataclass(frozen=True, slots=True)
class ResolvedAccess:
    """A component's effective access level together with what conferred it."""

    level: ComponentAccessLevel
    """The effective level."""

    source: AccessSource
    """Which input produced `level`. Grants win ties over the default."""

    origin: GrantOrigin | None = None
    """Whether the winning grant was the user's own or a group's, or `None` for a non-grant source."""

    group_id: UUID | None = None
    """The group that supplied the winning grant, when `origin` is `GROUP`."""


@dataclass(slots=True)
class AccessGrants:
    """A user's permission grants, merged across their direct grants and every group they belong to.

    Each mapping keeps the highest grant for a given target, so a component or tag reached through
    several grants resolves to the most permissive one. Fetch this once per user and reuse it to
    resolve access for many components without re-querying.
    """

    admin: bool = False
    """Whether the user is an admin and therefore has `MANAGE` on every component."""

    component: dict[str, Grant] = field(default_factory=dict)
    """Highest grant per component address target."""

    tag: dict[str, Grant] = field(default_factory=dict)
    """Highest grant per tag target."""

    everything: Grant | None = None
    """Highest grant applying to every component through an all-target grant, if any."""

    def _add(self, target_type: PermissionTargetType, target: str, grant: Grant):
        if target_type == PermissionTargetType.ALL:
            self.everything = _higher(self.everything, grant)
        elif target_type == PermissionTargetType.COMPONENT:
            self.component[target] = _higher(self.component.get(target), grant)
        elif target_type == PermissionTargetType.TAG:
            self.tag[target] = _higher(self.tag.get(target), grant)


def _higher(current: Grant | None, candidate: Grant) -> Grant:
    """Return whichever of `current` and `candidate` grants more access.

    On a tie the user's own grant is kept over a group's, since that is the one an operator would
    have to remove to change the outcome.
    """
    if current is None or candidate.level.order > current.level.order:
        return candidate

    if candidate.level.order == current.level.order and current.origin == GrantOrigin.GROUP:
        if candidate.origin == GrantOrigin.USER:
            return candidate

    return current


async def fetch_access_grants(database: Database, user: User) -> AccessGrants:
    """Fetch and merge every grant that applies to `user`.

    Issue one query for the user's direct grants, one for their group memberships, and one for the
    grants of all those groups, then merge them by target keeping the highest level. Admin users
    short-circuit with no grant queries since they hold `MANAGE` everywhere.

    Args:
        database: Database instance for querying grants.
        user: The user whose grants to fetch.

    Returns:
        The merged `AccessGrants` for the user.
    """
    grants = AccessGrants(admin=user.admin)
    if user.admin:
        return grants

    user_grants: list[UserPermission] = await database.user_permissions.where(user_id=user.id)
    for grant in user_grants:
        grants._add(
            grant.target_type,
            grant.target,
            Grant(level=grant.level, origin=GrantOrigin.USER),
        )

    memberships = await database.group_memberships.where(user_id=user.id)
    group_ids = [membership.group_id for membership in memberships]

    if group_ids:
        group_grants: list[GroupPermission] = await database.group_permissions.where(
            group_id=group_ids,
        )
        for grant in group_grants:
            grants._add(
                grant.target_type,
                grant.target,
                Grant(
                    level=grant.level,
                    origin=GrantOrigin.GROUP,
                    group_id=grant.group_id,
                ),
            )

    return grants


def resolve_access_from(
    grants: AccessGrants,
    *,
    address_chain: list[str],
    resolved_access: ComponentAccessLevel,
    inherited_tags: set[str],
) -> ComponentAccessLevel | None:
    """Compute the effective access level for one component from pre-fetched `grants`.

    Take the maximum across the component's default access, any component grant whose target is in
    the component's address chain, any tag grant whose target is in the component's inherited tags,
    and any all-target grant. Admins always receive `MANAGE`. All-target grants apply to every
    component regardless of address or tags.

    Args:
        grants: The user's grants, from `fetch_access_grants`.
        address_chain: Addresses from the component up to its top-level ancestor.
        resolved_access: The component's resolved default access from config inheritance.
        inherited_tags: Tags from the component and all its ancestors.

    Returns:
        The effective `ComponentAccessLevel`, or `None` if the user has no access.
    """
    resolved = resolve_access_detail_from(
        grants,
        address_chain=address_chain,
        resolved_access=resolved_access,
        inherited_tags=inherited_tags,
    )

    return None if resolved is None else resolved.level


def resolve_access_detail_from(
    grants: AccessGrants,
    *,
    address_chain: list[str],
    resolved_access: ComponentAccessLevel,
    inherited_tags: set[str],
) -> ResolvedAccess | None:
    """Resolve one component's effective access and report which input conferred it.

    Same resolution as `resolve_access_from`, but the result also names the winning input so
    callers can explain an access level rather than infer it. Where several inputs tie at the
    winning level, a grant is reported over the component's default, since removing that grant is
    what an operator would need to know about.

    Args:
        grants: The user's grants, from `fetch_access_grants`.
        address_chain: Addresses from the component up to its top-level ancestor.
        resolved_access: The component's resolved default access from config inheritance.
        inherited_tags: Tags from the component and all its ancestors.

    Returns:
        The effective level and its source, or `None` if the user has no access.
    """
    if grants.admin:
        return ResolvedAccess(ComponentAccessLevel.MANAGE, AccessSource.ADMIN)

    level: ComponentAccessLevel | None = None
    source = AccessSource.DEFAULT
    winner: Grant | None = None

    if resolved_access != ComponentAccessLevel.DENY:
        level = resolved_access

    def _take(grant: Grant, candidate_source: AccessSource) -> None:
        nonlocal level, source, winner
        if level is None or grant.level.order >= level.order:
            level = grant.level
            source = candidate_source
            winner = grant

    # Grants are considered after the default and replace it on ties, so an explicit grant is
    # reported even when the default already reached the same level.
    if grants.everything is not None:
        _take(grants.everything, AccessSource.ALL)

    # Tags before addresses so that on a tie the more specific component grant is the one reported.
    for tag in inherited_tags:
        granted = grants.tag.get(tag)
        if granted is not None:
            _take(granted, AccessSource.TAG)

    for address in address_chain:
        granted = grants.component.get(address)
        if granted is not None:
            _take(granted, AccessSource.COMPONENT)

    if level is None:
        return None

    if winner is None:
        return ResolvedAccess(level, source)

    return ResolvedAccess(level, source, winner.origin, winner.group_id)


async def resolve_access(
    *,
    database: Database,
    user: User,
    address_chain: list[str],
    resolved_access: ComponentAccessLevel,
    inherited_tags: set[str],
) -> ComponentAccessLevel | None:
    """Fetch `user`'s grants and resolve their effective access on a single component.

    A convenience wrapper over `fetch_access_grants` and `resolve_access_from` for callers
    resolving access on one component. To resolve many components for the same user, fetch the
    grants once and call `resolve_access_from` per component instead.

    Args:
        database: Database instance for querying grants.
        user: The user to check.
        address_chain: Addresses from the component up to its top-level ancestor.
        resolved_access: The component's resolved default access from config inheritance.
        inherited_tags: Tags from the component and all its ancestors.

    Returns:
        The effective `ComponentAccessLevel`, or `None` if the user has no access.
    """
    grants = await fetch_access_grants(database, user)
    return resolve_access_from(
        grants,
        address_chain=address_chain,
        resolved_access=resolved_access,
        inherited_tags=inherited_tags,
    )
