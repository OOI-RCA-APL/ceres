"""Engine-side helpers shared by the API's operations.

What remains is the logic the operations reuse, access resolution, the actor, the record
table selectors, and the filter limit, all free of any transport concern.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import AfterValidator
from pydantic_core import PydanticKnownError

from ceres.__internal__.core import RecordTable
from ceres.error import NotFoundError

if TYPE_CHECKING:
    from pydantic.main import IncEx

    from ceres.__internal__.entity import BaseEntityFilter
    from ceres.access import ResolvedAccess
    from ceres.address import Address
    from ceres.component import Component, ComponentAccessLevel, ComponentSystem
    from ceres.engine import Engine
    from ceres.user import User


def exclude_recursively(fields: Iterable[str]) -> IncEx:
    """Build a recursive Pydantic include/exclude dict that excludes the given fields at every
    nesting level.

    Args:
        fields: Field names to exclude.

    Returns:
        A nested dict suitable for `response_model_exclude`.
    """
    exclude: dict[str, Any] = {field: True for field in fields}
    exclude["__all__"] = exclude
    return exclude


EXCLUDE_PASSWORDS: IncEx = exclude_recursively(["password"])

RECORD_TABLES: Mapping[str, RecordTable] = {
    "messages": RecordTable.MESSAGES,
    "particles": RecordTable.PARTICLES,
    "alerts": RecordTable.ALERTS,
    "logs": RecordTable.LOGS,
}
"""The native table selector for each record table name."""

CREDENTIAL_FIELDS = ("secret", "password", "key_password")
"""Credential field names dropped from any serialized configuration.

The signing secret mints a token for any user, so serving it to an administrator hands over every
account. Dropped by name at every nesting level, which also covers a credential named this way
inside a component's own configuration.
"""


@dataclass(frozen=True, kw_only=True)
class Actor:
    """The acting context of a request: the user plus CLI/auth-disabled bypass state."""

    user: User | None
    unrestricted: bool
    """Whether the request bypasses all permission checks (CLI or auth disabled)."""

    @property
    def admin(self) -> bool:
        """Whether the actor has admin capability."""
        return self.unrestricted or (self.user is not None and self.user.admin)

    @property
    def authenticated(self) -> bool:
        """Whether the actor is an authenticated user or an unrestricted context."""
        return self.unrestricted or self.user is not None


def assert_found[T](value: T | None, /) -> T:
    """Return `value` if it is not ``None``, otherwise raise a not-found error.

    Raises:
        NotFoundError: If `value` is ``None``.
    """
    if value is None:
        raise NotFoundError()

    return value


async def get_component_access(
    engine: Engine,
    user: User | None,
    component: Component,
) -> ComponentAccessLevel | None:
    """Resolve the effective access level for a user on a component."""
    if user is None:
        return None

    from ceres.access import resolve_access

    system = component.system
    return await resolve_access(
        database=engine.database,
        user=user,
        address_chain=build_address_chain(system),
        resolved_access=system.get_resolved_access(),
        inherited_tags=system.get_inherited_tags(),
    )


async def get_engine_access_detail(engine: Engine, user: User | None) -> ResolvedAccess | None:
    """Resolve a user's access on the engine root, keeping what conferred the level.

    The engine root is the placement that workspaces spanning several components sit on. It has no
    component to resolve against, so it resolves like a component with no address chain and no
    tags, leaving the configured default access and any all-target grant. Authenticated users get
    `VIEW` unless the configuration lowers it, which mirrors how a component with no declared
    access behaves.

    Args:
        engine: Engine whose configuration and grants to resolve against.
        user: The user to check, or `None` for an unauthenticated caller.

    Returns:
        The effective level and its source, or `None` when there is no user or no access.
    """
    from ceres.access import fetch_access_grants, resolve_access_detail_from
    from ceres.component import ComponentAccessLevel

    if user is None:
        return None

    default = (
        engine.default_access if engine.default_access is not None else ComponentAccessLevel.VIEW
    )
    grants = await fetch_access_grants(engine.database, user)
    return resolve_access_detail_from(
        grants,
        address_chain=[],
        resolved_access=default,
        inherited_tags=set(),
    )


async def get_engine_access(engine: Engine, user: User | None) -> ComponentAccessLevel | None:
    """Resolve the effective access level for a user on the engine root.

    Args:
        engine: Engine whose configuration and grants to resolve against.
        user: The user to check, or `None` for an unauthenticated caller.

    Returns:
        The effective `ComponentAccessLevel`, or `None` when there is no user or no access.
    """
    resolved = await get_engine_access_detail(engine, user)
    return resolved.level if resolved is not None else None


async def get_components_access_detail(
    engine: Engine,
    user: User | None,
    components: Iterable[Component],
) -> dict[Address, ResolvedAccess | None]:
    """Resolve access across many components, keeping what conferred each level.

    Args:
        engine: The engine whose database holds the grants.
        user: The user to check, or `None` for an unauthenticated caller with no access.
        components: The components to resolve access for.

    Returns:
        A mapping from each component's address to its resolved level and source, or `None` where
        the user has no access.
    """
    if user is None:
        return {component.system.address: None for component in components}

    from ceres.access import fetch_access_grants, resolve_access_detail_from

    grants = await fetch_access_grants(engine.database, user)

    result: dict[Address, ResolvedAccess | None] = {}
    for component in components:
        system = component.system
        result[system.address] = resolve_access_detail_from(
            grants,
            address_chain=build_address_chain(system),
            resolved_access=system.get_resolved_access(),
            inherited_tags=system.get_inherited_tags(),
        )

    return result


async def get_components_access(
    engine: Engine,
    user: User | None,
    components: Iterable[Component],
) -> dict[Address, ComponentAccessLevel | None]:
    """Resolve the effective access level for a user across many components in one grant fetch.

    Fetch the user's grants once, then resolve each component in memory. Prefer this over calling
    `get_component_access` in a loop, which re-queries the grants for every component.

    Args:
        engine: The engine whose database holds the grants.
        user: The user to check, or `None` for an unauthenticated caller with no access.
        components: The components to resolve access for.

    Returns:
        A mapping from each component's address to its effective level, or `None` where the user
        has no access.
    """
    if user is None:
        return {component.system.address: None for component in components}

    from ceres.access import fetch_access_grants, resolve_access_from

    grants = await fetch_access_grants(engine.database, user)

    result: dict[Address, ComponentAccessLevel | None] = {}
    for component in components:
        system = component.system
        result[system.address] = resolve_access_from(
            grants,
            address_chain=build_address_chain(system),
            resolved_access=system.get_resolved_access(),
            inherited_tags=system.get_inherited_tags(),
        )

    return result


def build_address_chain(system: ComponentSystem) -> list[str]:
    """Build the list of addresses from a component up to its top-level ancestor."""
    chain: list[str] = []
    current: ComponentSystem | None = system
    while current is not None:
        chain.append(str(current.address))
        current = current.parent

    return chain


def Limit[FilterT: BaseEntityFilter](max: int) -> AfterValidator:
    """Create a Pydantic `AfterValidator` that caps a filter's `limit` field at `max`.

    If the filter has no limit set, default it to `max`. If the limit exceeds `max`, raise a
    validation error.

    Args:
        max: The maximum allowed value for the filter's `limit` field.

    Returns:
        An `AfterValidator` that enforces the limit constraint.
    """

    def validate_limit(filter: FilterT) -> FilterT:
        if filter.limit is None:
            filter = filter.model_copy(update={"limit": max})
        elif filter.limit > max:
            raise PydanticKnownError("less_than_equal", {"le": max})

        return filter

    return AfterValidator(validate_limit)
