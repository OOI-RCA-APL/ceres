from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ceres.component import ComponentAccessLevel
from ceres.permission import PermissionTargetType

if TYPE_CHECKING:
    from ceres.database import Database
    from ceres.permission import GroupPermission, UserPermission
    from ceres.user import User

__all__ = [
    "AccessGrants",
    "fetch_access_grants",
    "resolve_access",
    "resolve_access_from",
]


@dataclass(slots=True)
class AccessGrants:
    """A user's permission grants, merged across their direct grants and every group they belong to.

    Each mapping keeps the highest level granted for a given target, so a component or tag reached
    through several grants resolves to the most permissive one. Fetch this once per user and reuse
    it to resolve access for many components without re-querying.
    """

    admin: bool = False
    """Whether the user is an admin and therefore has `MANAGE` on every component."""

    component: dict[str, ComponentAccessLevel] = field(default_factory=dict)
    """Highest level granted per component address target."""

    tag: dict[str, ComponentAccessLevel] = field(default_factory=dict)
    """Highest level granted per tag target."""

    everything: ComponentAccessLevel | None = None
    """Highest level granted to every component through an all-target grant, if any."""

    def _add(self, target_type: PermissionTargetType, target: str, level: ComponentAccessLevel):
        if target_type == PermissionTargetType.ALL:
            self.everything = _higher(self.everything, level)
        elif target_type == PermissionTargetType.COMPONENT:
            self.component[target] = _higher(self.component.get(target), level)
        elif target_type == PermissionTargetType.TAG:
            self.tag[target] = _higher(self.tag.get(target), level)


def _higher(
    current: ComponentAccessLevel | None,
    candidate: ComponentAccessLevel,
) -> ComponentAccessLevel:
    """Return whichever of `current` and `candidate` grants more access."""
    if current is None or candidate.order > current.order:
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
        grants._add(grant.target_type, grant.target, grant.level)

    memberships = await database.group_memberships.where(user_id=user.id)
    group_ids = [membership.group_id for membership in memberships]

    if group_ids:
        group_grants: list[GroupPermission] = await database.group_permissions.where(
            group_id=group_ids,
        )
        for grant in group_grants:
            grants._add(grant.target_type, grant.target, grant.level)

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
    if grants.admin:
        return ComponentAccessLevel.MANAGE

    level = grants.everything

    if resolved_access != ComponentAccessLevel.DENY:
        level = _higher(level, resolved_access)

    for address in address_chain:
        granted = grants.component.get(address)
        if granted is not None:
            level = _higher(level, granted)

    for tag in inherited_tags:
        granted = grants.tag.get(tag)
        if granted is not None:
            level = _higher(level, granted)

    return level


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
