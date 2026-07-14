from __future__ import annotations

from typing import TYPE_CHECKING

from ceres.component import ComponentAccessLevel
from ceres.permission import PermissionTargetType

if TYPE_CHECKING:
    from ceres.database import Database
    from ceres.user import User

__all__ = [
    "resolve_access",
]


async def resolve_access(
    *,
    database: Database,
    user: User,
    address_chain: list[str],
    resolved_access: ComponentAccessLevel,
    inherited_tags: set[str],
) -> ComponentAccessLevel | None:
    """Compute the effective access level for a user on a component.

    Take the maximum across the component's default access, direct user grants,
    user tag grants, user all-grants, group component grants, group tag grants,
    and group all-grants. Admin users always receive `MANAGE` regardless of
    grants. All-grants apply to every component regardless of address or tags.

    Args:
        database: Database instance for querying grants.
        user: The user to check.
        address_chain: List of addresses from the component up to its top-level
            ancestor (e.g., `["sensors.nortek.vector", "sensors.nortek", "sensors"]`).
        resolved_access: The component's resolved default access (from config
            inheritance).
        inherited_tags: Tags from the component and all its ancestors.

    Returns:
        The effective `ComponentAccessLevel`, or `None` if the user has no access.
    """
    if user.admin:
        return ComponentAccessLevel.MANAGE

    levels: list[ComponentAccessLevel] = []

    if resolved_access != ComponentAccessLevel.DENY:
        levels.append(resolved_access)

    if address_chain:
        user_grants = await database.user_permissions.where(
            user_id=user.id,
            target_type=PermissionTargetType.COMPONENT,
        )
        for grant in user_grants:
            if grant.target in address_chain:
                levels.append(grant.level)

    if inherited_tags:
        user_tag_grants = await database.user_permissions.where(
            user_id=user.id,
            target_type=PermissionTargetType.TAG,
        )
        for grant in user_tag_grants:
            if grant.target in inherited_tags:
                levels.append(grant.level)

    user_all_grants = await database.user_permissions.where(
        user_id=user.id,
        target_type=PermissionTargetType.ALL,
    )
    for grant in user_all_grants:
        levels.append(grant.level)

    memberships = await database.group_memberships.where(user_id=user.id)
    group_ids = [membership.group_id for membership in memberships]

    if group_ids:
        if address_chain:
            for group_id in group_ids:
                group_grants = await database.group_permissions.where(
                    group_id=group_id,
                    target_type=PermissionTargetType.COMPONENT,
                )
                for grant in group_grants:
                    if grant.target in address_chain:
                        levels.append(grant.level)

        if inherited_tags:
            for group_id in group_ids:
                group_tag_grants = await database.group_permissions.where(
                    group_id=group_id,
                    target_type=PermissionTargetType.TAG,
                )
                for grant in group_tag_grants:
                    if grant.target in inherited_tags:
                        levels.append(grant.level)

        for group_id in group_ids:
            group_all_grants = await database.group_permissions.where(
                group_id=group_id,
                target_type=PermissionTargetType.ALL,
            )
            for grant in group_all_grants:
                levels.append(grant.level)

    if not levels:
        return None

    return max(levels, key=lambda level: level.order)
